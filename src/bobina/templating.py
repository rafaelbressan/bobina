"""Front matter + Jinja (sandboxed) + CLDR filters + persistent counters.

Safety model (FORMAT.md §7): every `{{ expression }}` becomes a *placeholder* before Markdown is
parsed and is substituted back as literal text afterwards. Data therefore never changes the
document structure, is never evaluated again, and cannot produce raw printer bytes.
`| markdown` is the explicit opt-in to interpret a value as Markdown (raw blocks still removed).
"""

from __future__ import annotations

import calendar
import contextlib
import functools
import math
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import yaml
from babel import Locale
from babel import dates as bdates
from babel import numbers as bnumbers
from jinja2 import ChainableUndefined, TemplateSyntaxError, Undefined, UndefinedError, nodes
from jinja2.compiler import CodeGenerator
from jinja2.exceptions import SecurityError as JinjaSecurityError
from jinja2.runtime import LoopContext, Macro
from jinja2.sandbox import ImmutableSandboxedEnvironment
from jinja2.utils import Namespace

from . import paths
from .nudges import Nudges, SecurityError

PH_OPEN, PH_CLOSE = "", ""
PH_RE = re.compile(PH_OPEN + r"(\d+)" + PH_CLOSE)
MAX_ITER = 2000  # loop steps: every {% for %} step, recursive loop() item, range() step, number taken
MAX_OUTPUT = 2_000_000  # characters
MAX_CALLS = 10_000  # macro calls (a recursive macro that branches is exponential)
MAX_SECONDS = 10  # one render (a label of a batch, a document): a usual one takes milliseconds
RESERVED = {
    "bob",
    "profile",
    "locale",
    "lang",  # alias of locale (a natural guess)
    "timezone",
    "fonts",
    "size",
    "align",
    "image",
    "tasks",
    "counters",
    "allow",
    "template",
    "fields",
    "labels",
}


class Tainted(str):
    """A value that came from outside the document (--data, --set). String operations keep the mark, so a
    filter or a method (`p | lower`, `p.strip()`, `p[1:]`) cannot launder data into an image path."""

    def __getattribute__(self, name):
        attr = super().__getattribute__(name)
        if name in _STR_METHODS:

            def kept(*a, **k):
                return taint(attr(*a, **k))

            return kept
        return attr

    def __add__(self, other):
        return Tainted(str.__add__(self, other))

    def __radd__(self, other):
        return Tainted(str(other) + str.__str__(self))

    def __getitem__(self, key):
        return Tainted(str.__getitem__(self, key))

    def __mod__(self, other):
        return Tainted(str.__mod__(self, other))


_STR_METHODS = {
    "capitalize", "casefold", "center", "expandtabs", "format", "format_map", "join", "ljust", "lower", "lstrip",
    "partition", "removeprefix", "removesuffix", "replace", "rjust", "rpartition", "rsplit", "rstrip", "split",
    "splitlines", "strip", "swapcase", "title", "translate", "upper", "zfill",
}  # fmt: skip


def taint(value):
    """Marks a result derived from data: strings become Tainted, lists/tuples element by element."""
    if isinstance(value, (Tainted, MdSafe)):
        return value
    if isinstance(value, str):
        return Tainted(value)
    if isinstance(value, (list, tuple)):
        return type(value)(taint(v) for v in value)
    return value


def _has_taint(x) -> bool:
    if isinstance(x, Tainted):
        return True
    if isinstance(x, (list, tuple)):
        return any(_has_taint(v) for v in x)
    if isinstance(x, dict):
        return any(_has_taint(v) for v in x.values())
    return False


def _data_texts(x) -> list[str]:
    if isinstance(x, Tainted):
        return [str.__str__(x)]
    if isinstance(x, dict):
        return [t for v in x.values() for t in _data_texts(v)]
    if isinstance(x, (list, tuple)):
        return [t for v in x for t in _data_texts(v)]
    return []


def keep_taint(f):
    """Wraps a Jinja filter: if any argument is data, the result is data too."""
    import functools

    @functools.wraps(f)  # keeps jinja_pass_arg (filters that receive the environment or the context)
    def wrapper(*a, **k):
        r = f(*a, **k)
        return taint(r) if any(_has_taint(x) for x in (*a, *k.values())) else r

    return wrapper


class MdSafe(str):
    """A value explicitly marked to be interpreted as Markdown."""


@dataclass
class Value:
    text: str
    tainted: bool = False


@dataclass
class Rendered:
    text: str
    values: list[Value]
    counters: CounterStore
    data: list[str] = field(default_factory=list)  # every --data/--set value given to this render

    def resolve(self, s: str) -> str:
        for _ in range(4):  # defaults may nest placeholders once
            if PH_OPEN not in s:
                break
            s = PH_RE.sub(lambda m: self.values[int(m.group(1))].text, s)
        return s

    def tainted_in(self, s: str) -> bool:
        seen = set(PH_RE.findall(s))
        for i in list(seen):
            seen |= set(PH_RE.findall(self.values[int(i)].text))
        if any(self.values[int(i)].tainted for i in seen):
            return True
        # last line of defence: a data value that reached the text some other way ('img/' ~ p joins plain strings)
        if not seen:
            return False
        resolved = PH_RE.sub(lambda m: self.values[int(m.group(1))].text, s).casefold()
        texts = [v.text for v in self.values if v.tainted] + self.data
        return any(len(t) >= 3 and t.casefold() in resolved for t in texts)


# ---------------------------------------------------------------- front matter

FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.S)


def split_front_matter(text: str) -> tuple[dict, str, int]:
    """Returns (meta, body, number of lines taken by the front matter)."""
    m = FM_RE.match(text)
    if not m:
        return {}, text, 0
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"front matter is not valid YAML: {e}") from e
    if not isinstance(meta, dict):
        raise ValueError("front matter must be a mapping (key: value)")
    return meta, text[m.end() :], m.group(0).count("\n")


# ---------------------------------------------------------------- counters

FMT_RE = re.compile(r"^[^{}]*\{:[^{}]*\}[^{}]*$")


def letters(n: int) -> str:
    s = ""
    n = int(n)
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class CounterConflict(ValueError):
    """Two parts of one job declare the same counter differently (E304)."""

    code = "E304"


class CounterStore:
    """The values of {{ seq.NAME }}.

    Preview, check and dry runs only look (reserve=False): values come from a snapshot of counters.json and
    nothing is written. A print reserves (reserve=True, decided 07/11): each value is taken under the file lock
    and counters.json moves on at once, so two prints at the same time never get the same number. A job that is
    not printed gives its numbers back (release) when no other job took numbers after it; otherwise they stay
    skipped. Numbers never repeat; a cancelled job may leave a gap."""

    def __init__(self, decl: dict | None, nudges: Nudges, path=None, reserve: bool = False):
        from . import fileio

        self.path = path or paths.state_dir() / "counters.json"
        self.decl = {}
        self.declare(decl)
        self.nudges = nudges
        self.reserve = reserve
        self.state = fileio.read_json(self.path, {})  # a damaged file is an error: never restart the numbering
        self.used: dict[str, list[int]] = {}
        self._before: dict[str, object] = {}  # reserve mode: the file's value before this job's first number
        self._wrote: dict[str, int] = {}  # the value this job left in the file
        self._contiguous: dict[str, bool] = {}  # no other job took numbers between this job's reservations
        self.done = False

    def declare(self, decl: dict | None) -> None:
        """A later part of the job (--then) brings its own counters: add them. The same counter declared
        differently by two parts is an error: one strip cannot number the same counter two ways."""
        if decl is not None and not isinstance(decl, dict):
            raise ValueError(f"counters: must be a mapping (name: {{start: 1}}), got {type(decl).__name__}")
        for name, c in (decl or {}).items():
            if name in self.decl and self.decl[name] != c:
                raise CounterConflict(
                    f"counter '{name}' is declared differently in two parts: {self.decl[name]} and {c}"
                )
            self.decl[name] = c

    def cfg(self, name: str) -> dict:
        c = self.decl.get(name) or {}
        return c if isinstance(c, dict) else {}

    def _series(self, name: str, cur: int, n: int) -> tuple[list[int], int]:
        """n values starting at `cur` (the counter's next value) and the next value after them."""
        c = self.cfg(name)
        start, step = int(c.get("start", 1)), int(c.get("step", 1)) or 1
        stop, wrap = c.get("stop"), bool(c.get("wrap", False))

        def past(v):
            return stop is not None and ((step > 0 and v > int(stop)) or (step < 0 and v < int(stop)))

        out, v = [], cur
        for _ in range(n):
            if past(v):
                if wrap:
                    v = start
                else:
                    self.nudges.add(
                        "M140",
                        f"counter '{name}' passed stop={stop} (value {v})",
                        suggestion="raise stop, set wrap: true, or bobina seq reset",
                    )
            out.append(v)
            v += step
        if wrap and past(v):
            v = start
        return out, v

    def _next_values(self, name: str, n: int) -> list[int]:
        start = int(self.cfg(name).get("start", 1))
        used = self.used.setdefault(name, [])
        if not self.reserve:
            if used:
                _, cur = self._series(name, used[-1], 1)
            else:
                cur = self.state.get(name, start)
            out, _ = self._series(name, cur, n)
            used += out
            return out
        from . import fileio

        def take(state):
            cur = state.get(name, start)
            if name not in self._before:
                self._before[name] = state.get(name, None)
                self._contiguous[name] = True
            elif cur != self._wrote.get(name):
                self._contiguous[name] = False  # another print took numbers in between
            out, nxt = self._series(name, cur, n)
            state[name] = nxt
            self._wrote[name] = nxt
            return out

        out = fileio.locked_update(self.path, take, durable=False)  # commit() makes it durable
        used += out
        return out

    def fmt(self, name: str, v: int) -> str:
        c = self.cfg(name)
        if c.get("style") == "letters":
            return letters(v)
        if c.get("style") == "hex":
            return format(v, "X")
        f = c.get("format")
        if f:
            if not FMT_RE.match(str(f)):
                raise SecurityError(
                    "M311",
                    f'counter format \'{f}\' must contain exactly one {{:spec}}, e.g. "{{:d}}" or "A-{{:03}}"',
                )
            return str(f).format(v)
        return str(v)

    def reserved(self) -> dict[str, list[str]]:
        return {k: [self.fmt(k, v) for v in vs] for k, vs in self.used.items() if vs}

    def commit(self):
        """The job was printed: its numbers are spent. In reserve mode they already are; the file is synced."""
        from . import fileio

        if self.done or not any(self.used.values()):
            self.done = True
            return
        if self.reserve:
            fileio.fsync_file(self.path)
        else:  # a print path that did not reserve: move the counters on now, relative to the file as it is

            def advance(state):
                for name, vs in self.used.items():
                    if vs:
                        start = int(self.cfg(name).get("start", 1))
                        _, state[name] = self._series(name, state.get(name, start), len(vs))

            fileio.locked_update(self.path, advance)
        self.done = True

    def release(self):
        """The job was not printed: give the numbers back if no other print took numbers after them."""
        from . import fileio

        if self.done or not self.reserve or not self._wrote:
            self.done = True
            return

        def give_back(state):
            for name, wrote in self._wrote.items():
                if self._contiguous.get(name) and state.get(name) == wrote:
                    if self._before[name] is None:
                        state.pop(name, None)
                    else:
                        state[name] = self._before[name]

        fileio.locked_update(self.path, give_back)
        self.done = True


class Budget:
    """n steps (loop iterations, macro calls) and, with seconds, a deadline for the whole render: a loop of
    filters over long values spends few steps but can still take minutes."""

    def __init__(self, n=MAX_ITER, what="loop iterations", seconds: float | None = None):
        self.n, self.limit, self.what = n, n, what
        self.seconds = seconds
        self.deadline = time.monotonic() + seconds if seconds else None

    def spend(self, k=1):
        self.n -= k
        if self.n < 0:
            raise SecurityError("M313", f"more than {self.limit} {self.what}")
        self.tick()

    def tick(self):
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise SecurityError("M313", f"the template took more than {self.seconds:g} s to render")

    @contextlib.contextmanager
    def paused(self):
        """Time spent waiting for something else (the counters file of another print) is not the template's."""
        start = time.monotonic()
        try:
            yield
        finally:
            if self.deadline is not None:
                self.deadline += time.monotonic() - start


def too_big(v) -> bool:
    """A value no template needs: longer than the whole output may be (strings, lists, dicts)."""
    return isinstance(v, (str, list, tuple, dict)) and len(v) > MAX_OUTPUT


def _refuse_size():
    raise SecurityError("M313", f"a value grew beyond {MAX_OUTPUT // 1_000_000} MB while rendering")


def check_size(v):
    if too_big(v):
        _refuse_size()
    return v


def check_estimate(n: int) -> None:
    """Refuses an operation whose result would be longer than MAX_OUTPUT, before it is built."""
    if n > MAX_OUTPUT:
        _refuse_size()


MAX_BITS = 100_000  # integers: about 30 000 digits, far beyond any amount, and quick to compute


def check_bits(n: int) -> None:
    if n > MAX_BITS:
        raise SecurityError("M313", "a number too large to compute")


class SafeRange:
    """range() for templates: lazy, and each step taken (a loop, | list, | sum …) spends the loop budget, so
    range(10**9) | length is free and range(10**9) | list stops at the limit."""

    def __init__(self, r: range, budget: Budget):
        self._r, self._budget = r, budget

    def __iter__(self):
        for x in self._r:
            self._budget.spend()
            yield x

    def __reversed__(self):
        return iter(SafeRange(self._r[::-1], self._budget))

    def __len__(self):
        return len(self._r)

    def __contains__(self, x):
        return x in self._r

    def __getitem__(self, k):
        return SafeRange(self._r[k], self._budget) if isinstance(k, slice) else self._r[k]

    def __repr__(self):
        return repr(self._r)


class Taken(list):
    """seq.NAME.take(n): the numbers were paid for when taken, so the first loop over them is free."""

    fresh = True


def _ints(values) -> list[int]:
    return [v for v in values if isinstance(v, int) and not isinstance(v, bool)]


def _strlen(v) -> int:
    return len(v) if isinstance(v, str) else 0


_WIDTH_METHODS = {"center", "ljust", "rjust", "zfill", "expandtabs"}
_PRINTF_SIZES = re.compile(r"%(?:\([^)]*\))?[-+ #0]*(\d+|\*)?(?:\.(\d+|\*))?")
_FORMAT_SPECS = re.compile(r"\{[^{}]*:([^{}]*)\}")
_NESTED_SPEC = re.compile(r"\{[^{}]*:[^{}]*\{")


def check_format(fmt: str, args=(), kwargs=None) -> None:
    """A format string cannot ask for a field wider than the output may be: '%100000000d', '%*d' % (10**9, 1),
    '{:>100000000}', '{:{w}}'.format(1, w=10**9), format_map({'w': 10**9})."""
    sizes = [n for w, p in _PRINTF_SIZES.findall(fmt) for n in (w, p) if n]
    nums = [int(n) for n in sizes if n != "*"]
    nums += [int(n) for spec in _FORMAT_SPECS.findall(fmt) for n in re.findall(r"\d+", spec)]
    if "*" in sizes or _NESTED_SPEC.search(fmt):  # the width comes from the arguments
        nums += _ints((*args, *(kwargs or {}).values()))
    if any(n > MAX_OUTPUT for n in nums):
        raise SecurityError("M313", f"a format asks for a field wider than {MAX_OUTPUT // 1_000_000} MB")


def check_widths(args) -> None:
    if any(a > MAX_OUTPUT for a in _ints(args)):
        raise SecurityError("M313", f"a width beyond {MAX_OUTPUT // 1_000_000} MB")


def join_size(sep, items) -> int:
    """The length of sep.join(items), from what is already there (a generator: 0, checked afterwards)."""
    if not hasattr(items, "__len__") or isinstance(items, (str, SafeRange)):
        return len(items) * _strlen(sep) if isinstance(items, str) else 0
    return _strlen(sep) * max(0, len(items) - 1) + sum(_strlen(x) for x in items)


def replace_size(s, old, new, count=-1) -> int:
    if not (isinstance(s, str) and isinstance(old, str) and isinstance(new, str)):
        return 0
    n = s.count(old) if old else len(s) + 1
    if isinstance(count, int) and count >= 0:
        n = min(n, count)
    return len(s) + n * max(0, len(new) - len(old))


def _lines(s) -> int:
    return str(s).count("\n") + 1


class _CountingCodeGenerator(CodeGenerator):
    """Compiles templates so that no work escapes bobina's limits: every {% for x in it %} becomes
    {% for x in environment.bobina_loop(it) %}, every `a ~ b` environment.bobina_join((a, b)), and every
    {% set x = v %} checks the size of v. A template cannot reach these names."""

    def visit_Template(self, node, frame=None):
        def call(name, arg, lineno):
            return nodes.Call(nodes.EnvironmentAttribute(name), [arg], [], None, None, lineno=lineno)

        for f in node.find_all(nodes.For):
            f.iter = call("bobina_loop", f.iter, f.lineno)
        for a in node.find_all(nodes.Assign):
            a.node = call("bobina_value", a.node, a.lineno)
        super().visit_Template(node, frame)

    def visit_Concat(self, node, frame):  # no constant folding: the result size is checked at render time
        self.write("environment.bobina_join((")
        for arg in node.nodes:
            self.visit(arg, frame)
            self.write(", ")
        self.write("))")


class Sandbox(ImmutableSandboxedEnvironment):
    """Jinja's sandbox plus bobina's limits (FORMAT.md §7, SECURITY.md): every {% for %} step and every macro call
    spends a budget, every operation ticks the render's deadline, and no operation may build a value longer than
    the whole output may be. Without this a short template could loop forever over a string or allocate
    gigabytes ('a' * 10**10) before any output is counted."""

    intercepted_binops = frozenset({"+", "-", "*", "/", "//", "%", "**"})

    def __init__(self, loops: Budget, calls: Budget, **kw):
        super().__init__(**kw)
        self.loops, self.calls = loops, calls
        self.code_generator_class = _CountingCodeGenerator
        self.concat = self.bobina_concat  # {% set %}…{% endset %}, macro bodies, {% filter %} blocks

    def bobina_loop(self, iterable):
        """Wraps the iterable of every {% for %} (see _CountingCodeGenerator)."""
        if isinstance(iterable, SafeRange):
            return iterable  # each step already spends
        if isinstance(iterable, Taken) and iterable.fresh:
            iterable.fresh = False
            return iterable
        return self._spending(iterable)

    def _spending(self, iterable):
        for x in iterable:
            self.loops.spend()
            yield x

    def bobina_value(self, value):
        """{% set x = value %}"""
        self.loops.tick()
        return check_size(value)

    def bobina_join(self, parts):
        """a ~ b ~ c: as Jinja's str_join, with its size known before it is joined."""
        self.loops.tick()
        texts = [str(p) for p in parts]
        check_estimate(sum(len(t) for t in texts))
        return "".join(texts)

    def bobina_concat(self, buffer):
        """The output of a block kept as a value: it stops growing at MAX_OUTPUT, as the document does."""
        out, size = [], 0
        for chunk in buffer:
            size += len(chunk)
            check_estimate(size)
            out.append(chunk)
        return "".join(out)

    def call_binop(self, context, operator, left, right):
        self.loops.tick()
        seq = (str, list, tuple)
        ints = isinstance(left, int) and isinstance(right, int)
        if operator == "*":
            if ints:
                check_bits(left.bit_length() + right.bit_length())
            else:
                n, s = (right, left) if isinstance(left, seq) else (left, right)
                if isinstance(s, seq) and isinstance(n, int):
                    check_estimate(len(s) * n)
        elif operator in ("+", "-"):
            if isinstance(left, seq) and isinstance(right, seq):
                check_estimate(len(left) + len(right))
            elif ints:
                check_bits(max(left.bit_length(), right.bit_length()) + 1)
        elif operator == "**" and isinstance(left, (int, float)) and isinstance(right, (int, float)):
            if abs(left) > 1 and right > 0 and right * math.log2(abs(left)) > MAX_BITS:
                check_bits(MAX_BITS + 1)
        elif operator == "%" and isinstance(left, str):
            check_format(left, right if isinstance(right, tuple) else (right,))
        return check_size(super().call_binop(context, operator, left, right))

    def call(__self, __context, __obj, *args, **kwargs):  # noqa: N805 - Jinja's signature
        __self.loops.tick()
        if isinstance(__obj, Macro):
            __self.calls.spend()
        elif isinstance(__obj, LoopContext) and args:  # loop(children) in a recursive loop
            args = (__self._spending(args[0]), *args[1:])
        for a in (*args, *kwargs.values()):
            check_size(a)
        method = getattr(__obj, "__wrapped__", __obj)  # the sandbox wraps str.format
        owner, name = getattr(method, "__self__", None), getattr(method, "__name__", "")
        if isinstance(owner, str):
            if name in _WIDTH_METHODS:
                check_widths((*args, *kwargs.values()))
            elif name == "format":
                check_format(owner, args, kwargs)
            elif name == "format_map" and args and isinstance(args[0], dict):
                check_format(owner, (), args[0])
            elif name == "join" and args:
                check_estimate(join_size(owner, args[0]))
            elif name == "replace" and len(args) >= 2:
                check_estimate(replace_size(owner, *args[:3]))
        return check_size(__self._bounded(super().call(__context, __obj, *args, **kwargs)))

    def _bounded(self, result):
        """A lazy result (a generator from map, batch, slice …) is drawn with the deadline ticking and stops at
        MAX_OUTPUT items, whatever consumes it (| list, | join, a loop)."""
        if isinstance(result, (str, bytes, list, tuple, dict)) or not hasattr(result, "__next__"):
            return result

        def items():
            for i, x in enumerate(result):
                if i % 256 == 0:
                    self.loops.tick()
                check_estimate(i)
                yield x

        return items()


def _size_guard(name: str, f, env: Sandbox):
    """Filters, like calls: no width or result beyond MAX_OUTPUT ('a' | center(10**9), '%9999999999d' | format),
    estimated before the work when the filter expands its input (join, replace, indent, wordwrap, batch, slice)."""

    @functools.wraps(f)  # keeps jinja_pass_arg
    def guarded(*a, **k):
        values = [*a[1 if getattr(f, "jinja_pass_arg", None) else 0 :]]  # not the env/context argument
        v, rest = (values[0] if values else None), values[1:]
        env.loops.tick()  # map/select call a filter per item: the deadline sees each one
        if name == "center":
            check_widths((*rest, *k.values()))
        elif name == "indent":
            width = rest[0] if rest else k.get("width", 4)
            check_widths([width])
            pad = len(width) if isinstance(width, str) else width if isinstance(width, int) else 0
            check_estimate(_strlen(v) + _lines(v) * pad)
        elif name == "format" and isinstance(v, str):
            check_format(v, rest, k)
        elif name == "join":
            check_estimate(join_size(rest[0] if rest else k.get("d", ""), v))
        elif name == "replace" and len(rest) >= 2:
            check_estimate(replace_size(v, *rest[:3], **({"count": k["count"]} if "count" in k else {})))
        elif name == "wordwrap":
            width = rest[0] if rest else k.get("width", 79)
            wrap = rest[2] if len(rest) > 2 else k.get("wrapstring") or "\n"
            if isinstance(width, int) and isinstance(wrap, str):
                check_estimate(_strlen(v) + (_strlen(v) // max(1, width) + 1) * len(wrap))
        elif name == "batch":
            count = rest[0] if rest else k.get("linecount", 0)
            fill = rest[1] if len(rest) > 1 else k.get("fill_with")
            if fill is not None:
                check_widths([count])  # the last batch is padded to `count` items
        elif name == "slice":
            count = rest[0] if rest else k.get("slices", 0)
            if isinstance(count, int) and count > MAX_ITER:
                raise SecurityError("M313", f"| slice into more than {MAX_ITER} parts")
        return check_size(env._bounded(f(*a, **k)))

    return guarded


class _BudgetNamespace(Namespace):
    """namespace(): {% set ns.s = ns.s ~ ns.s %} in a loop doubles a string; it stops at MAX_OUTPUT."""

    def __setitem__(self, name, value):
        super().__setitem__(name, check_size(value))


class Counter:
    def __init__(self, store: CounterStore, name: str, budget: Budget):
        self._store, self._name, self._budget, self._first = store, name, budget, None

    def __str__(self):
        if self._first is None:
            with self._budget.paused():
                self._first = self._store._next_values(self._name, 1)[0]
        return self._store.fmt(self._name, self._first)

    def take(self, n):
        n = int(n)
        if n < 1:  # take(0) or take(-5) would give loop steps back
            raise ValueError(f"template error: seq.{self._name}.take({n}): take at least 1 number")
        self._budget.spend(n)
        with self._budget.paused():
            values = self._store._next_values(self._name, n)
        return Taken(self._store.fmt(self._name, v) for v in values)


class Seq:
    def __init__(self, store, budget):
        self._store, self._budget, self._c = store, budget, {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._c:
            self._c[name] = Counter(self._store, name, self._budget)
        return self._c[name]


# ---------------------------------------------------------------- filters

STYLES = {"short", "medium", "long", "full"}


# words kept lowercase inside a title, by language ("Arroz da Fazenda", "Bread of the Day")
TITLE_SMALL = {
    "pt": {"a", "as", "o", "os", "e", "de", "da", "das", "do", "dos", "em", "na", "nas", "no", "nos", "com", "por",
           "para"},
    "es": {"a", "y", "e", "o", "de", "del", "la", "las", "el", "los", "en", "con", "por", "para"},
    "en": {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "with"},
    "fr": {"a", "à", "au", "aux", "de", "des", "du", "en", "et", "la", "le", "les", "ou", "sur"},
}  # fmt: skip
SMALL_CAPS = dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ", strict=True))


def _words(v) -> list[str]:
    import unicodedata

    s = unicodedata.normalize("NFKD", str(v))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)  # split camelCase
    return [w for w in re.split(r"[^A-Za-z0-9]+", s) if w]


def text_filters(loc: Locale) -> dict:
    """Case and shape of text, whatever the source wrote: upper/lower/capitalize/title come from Jinja."""
    import unicodedata

    small = TITLE_SMALL.get(loc.language, set())

    def titlecase(v):
        words = str(v).lower().split(" ")
        return " ".join(w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(words))

    def deaccent(v):
        s = unicodedata.normalize("NFKD", str(v))
        return unicodedata.normalize("NFC", "".join(c for c in s if not unicodedata.combining(c)))

    def camel(v):
        w = [x.lower() for x in _words(v)]
        return (w[0] + "".join(x.capitalize() for x in w[1:])) if w else ""

    return {
        "titlecase": titlecase,
        "deaccent": deaccent,
        "camel": camel,
        "pascal": lambda v: "".join(x.capitalize() for x in _words(v)),
        "snake": lambda v: "_".join(x.lower() for x in _words(v)),
        "kebab": lambda v: "-".join(x.lower() for x in _words(v)),
        "slug": lambda v: "-".join(x.lower() for x in _words(v)),
        "smallcaps": lambda v: "".join(SMALL_CAPS.get(c, c) if c.islower() else c for c in str(v)),
    }


NUMBER = re.compile(r"^(\D*?)([+-]?[\d.,\s]*\d)(\D*)$")
GROUPS = re.compile(r"\d{1,3}(?:([., ])\d{3})?(?:\1\d{3})*")  # 1 · 1.890 · 1 890 · 1,890,000: one mark only


def parse_number(v, decimal: str = ".") -> int | float | None:
    """A number from a value a person typed: 24.90, 149,90, R$ 1.890,00, 1 890, 3 dias. None when it is not one or
    is ambiguous, so the caller can warn instead of printing a wrong value. The last separator is the decimal one
    when the other kind comes before it (1.890,00), when it is the locale's (24,90 in Portuguese), when it is not
    followed by exactly 3 digits (24.90 anywhere) or when only zeros come before it (0.500); otherwise it groups
    thousands (1.890 in Portuguese), and groups must have 3 digits. Integers stay exact."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    core = number_core(v)
    if core is None:
        return None
    sign = "-" if core.startswith("-") or is_negative(v) else ""
    core = core.lstrip("+-")
    seps = [c for c in core if not c.isdigit()]
    dec = None
    if seps and seps[-1] != " " and seps.count(seps[-1]) == 1:
        whole, frac = core.rsplit(seps[-1], 1)
        if len(set(seps)) > 1 or seps[-1] == decimal or len(frac) != 3 or not whole.strip("0"):
            dec = seps[-1]
    whole, frac = core.rsplit(dec, 1) if dec else (core, "")
    if whole and not GROUPS.fullmatch(whole) and not whole.isdigit():
        return None
    digits = re.sub(r"\D", "", whole) or "0"
    if len(digits) > 30:
        return None
    return float(f"{sign}{digits}.{frac}") if dec else int(sign + digits)


def is_negative(v) -> bool:
    """A minus before the digits, also before a prefix (-R$ 10,00) or as the Unicode minus (−10)."""
    return bool(re.match(r"^[^\d]*[-\u2212]", str(v).strip()))


def number_core(v) -> str | None:
    """The digits and separators of a typed value, without its prefix or suffix (R$, BRL, kg)."""
    m = NUMBER.match(str(v).strip())
    return m.group(2).replace("\u00a0", " ").strip() if m else None


def two_readings(v, decimals: int = 2) -> tuple[str, str] | None:
    """(whole, frac) when a typed amount reads two ways: 1.890 is 1890 to a Brazilian and 1.89 to an American;
    R$ or BRL around it and a sign change nothing. parse_number settles it by the locale; money that is paid
    must not be settled by a guess, in any currency (1.500 BTC, 1.890 JPY, 1.500 KWD read two ways as well).
    Not for computed numbers (2.125 is a float) nor 0.500. decimals is kept for callers; it no longer
    exempts a currency."""
    if isinstance(v, (bool, int, float)):
        return None
    core = (number_core(v) or "").lstrip("+-")
    m = re.fullmatch(r"(\d{1,3})[.,](\d{3})", core)
    return (m.group(1), m.group(2)) if m and m.group(1).strip("0") else None


def ambiguity_message(raw, whole: str, frac: str) -> tuple[str, str]:
    """(message, suggestion) for an amount that reads two ways: both values, never a guess at one."""
    return (f"amount {raw} could mean {whole}{frac} or {float(f'{whole}.{frac}'):g}",
            f"write {whole}{frac} or {whole}.{frac},00 for thousands, or the amount with 2 decimals")  # fmt: skip


def make_filters(loc: Locale, tz: ZoneInfo, nudges: Nudges, explicit_locale: bool = True):
    decimal = bnumbers.get_decimal_symbol(loc)

    def num(v, where: str, then: str = "printed as it is"):
        """v as a number, or None (with M202) when it is not one. Empty and undefined are None, silently: M130
        and M131 already say a field is missing."""
        if isinstance(v, Undefined) or v is None or str(v).strip() == "":
            return None
        n = parse_number(v, decimal)  # read in the locale it is written in
        if n is None:
            nudges.add("M202", f"'{v}' is not a number ({where}): {then}",
                       suggestion="write digits, like 24.90 or 24,90")  # fmt: skip
        return n

    def typed(v) -> str:
        """The value as the person typed it: what a number filter prints when it is not a number."""
        return "" if v is None or isinstance(v, Undefined) else str(v)

    def as_dt(v):
        if isinstance(v, datetime):
            return v
        if isinstance(v, date):
            return datetime(v.year, v.month, v.day, tzinfo=tz)
        return datetime.fromisoformat(str(v)).replace(tzinfo=tz)

    def strftime_l(dt, fmt):
        rep = {
            "%B": bdates.get_month_names("wide", locale=loc)[dt.month],
            "%b": bdates.get_month_names("abbreviated", locale=loc)[dt.month],
            "%A": bdates.get_day_names("wide", locale=loc)[dt.weekday()],
            "%a": bdates.get_day_names("abbreviated", locale=loc)[dt.weekday()],
        }
        for k, v in rep.items():
            fmt = fmt.replace(k, v.replace("%", "%%"))
        return dt.strftime(fmt)

    def f_date(v, fmt="medium"):
        dt = as_dt(v)
        if fmt in STYLES:
            return bdates.format_date(dt, format=fmt, locale=loc)
        if "%" in fmt:
            return strftime_l(dt, fmt)
        if "YYYY" in fmt or "DD" in fmt:
            nudges.add(
                "M201",
                f"pattern '{fmt}': YYYY is week-year and DD day-of-year in CLDR",
                suggestion="use yyyy and dd (e.g. dd/MM/yyyy)",
            )
        return bdates.format_datetime(dt, fmt, tzinfo=tz, locale=loc)

    def f_time(v, fmt="short"):
        dt = as_dt(v)
        if fmt in STYLES:
            return bdates.format_time(dt, format=fmt, tzinfo=tz, locale=loc)
        return f_date(dt, fmt)

    def f_datetime(v, fmt="short"):
        dt = as_dt(v)
        if fmt in STYLES:
            return bdates.format_datetime(dt, format=fmt, tzinfo=tz, locale=loc)
        return f_date(dt, fmt)

    def f_add(v, days=0, hours=0, minutes=0, weeks=0, months=0, years=0):
        start = as_dt(v)
        amounts = {"days": days, "hours": hours, "minutes": minutes, "weeks": weeks, "months": months, "years": years}
        n = {k: num(a, f"add {k}", "counted as 0") or 0 for k, a in amounts.items()}
        try:
            dt = start + timedelta(days=n["days"], hours=n["hours"], minutes=n["minutes"], weeks=n["weeks"])
            if n["months"] or n["years"]:
                m = dt.month - 1 + int(n["months"]) + 12 * int(n["years"])
                y, m = dt.year + m // 12, m % 12 + 1
                dt = dt.replace(year=y, month=m, day=min(dt.day, calendar.monthrange(y, m)[1]))
        except (OverflowError, ValueError):
            nudges.add("M202", f"add({', '.join(f'{k}={a}' for k, a in amounts.items() if a)}) leaves the calendar: "
                       "the date is printed unchanged", suggestion="use a smaller amount")  # fmt: skip
            return start
        return dt

    def two_ways(v, where: str, payment: bool) -> bool:
        """An amount like 1.890 reads two ways. A payment never takes it; a price takes it only when the document says
        its locale (the author's intent: 1.890 is what that language means), never by the machine's locale."""
        both = two_readings(v) if (payment or not explicit_locale) else None
        if both:
            msg, hint = ambiguity_message(v, *both)
            hint += "" if payment else ", or write locale: in the document (then 1.890 means what it means there)"
            nudges.add("M202", f"{msg} ({where}): printed as it is", suggestion=hint)
        return bool(both)

    def f_currency(v, code="BRL"):
        from .pay import money

        if two_ways(v, "currency", payment=False):
            return typed(v)
        n = num(v, "currency")
        if n is None:
            return typed(v)
        return money(None, n, {"currency": code}, loc)  # as a payment caption: BTC, jpy, R$

    def f_number(v, decimals=None):
        n = num(v, "number")
        if n is None:
            return typed(v)
        if decimals is None:
            return bnumbers.format_decimal(n, locale=loc)
        return bnumbers.format_decimal(
            n, format="#,##0." + "0" * int(decimals) if int(decimals) else "#,##0", locale=loc
        )

    def f_percent(v):
        n = num(v, "percent")
        if n is not None and typed(v).strip().endswith("%"):
            n = n / 100  # "10%" is 0.10, not 10
        return typed(v) if n is None else bnumbers.format_percent(n, locale=loc)

    def f_payname(v):
        from .pay import SCHEMES

        s = SCHEMES.get(str(v).strip().lower())
        return s.title if s and s.title else typed(v)

    def f_paymoney(v, scheme=""):
        from .pay import SCHEMES, money

        s = SCHEMES.get(str(scheme).strip().lower())
        if two_ways(v, "paymoney", payment=True):  # the same refusal as the pay block next to it
            return typed(v)
        n = num(v, "paymoney")
        if n is None:
            return typed(v)
        return money(s, n, {}, loc)

    def f_float(v, default=0.0):
        n = num(v, "float", f"counted as {default}")
        return default if n is None else float(n)

    def f_int(v, default=0, base=10):
        if base != 10:
            from jinja2.filters import do_int

            return do_int(v, default, base)
        n = num(v, "int", f"counted as {default}")
        return default if n is None else int(n)

    def f_markdown(v):
        text = str(v)
        cleaned = RAW_FENCE.sub("", text)
        if cleaned != text:
            nudges.add("M121", "a raw block inside a variable was removed")
        if isinstance(v, Tainted):  # data never chooses files: no images, no image fences
            c2 = IMAGE_FENCE.sub("", IMAGE_MD.sub(lambda m: m.group(1), cleaned))
            if c2 != cleaned:
                nudges.add("M122", "an image inside a --data/--set value was removed (data cannot choose files)")
            cleaned = c2
        if isinstance(v, Tainted):
            nudges.add("M120", "a value from --data/--set is rendered as Markdown (| markdown)")
        return MdSafe(cleaned)

    return {
        **text_filters(loc),
        "date": f_date,
        "time": f_time,
        "datetime": f_datetime,
        "add": f_add,
        "currency": f_currency,
        "number": f_number,
        "percent": f_percent,
        "float": f_float,
        "payname": f_payname,
        "paymoney": f_paymoney,
        "int": f_int,
        "markdown": f_markdown,
        "letters": letters,
    }


IMAGE_MD = re.compile(r"!\[([^\]]*)\]\([^)]*\)(\{[^}]*\})?")
IMAGE_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*image\b.*?^[ \t]*\1[ \t]*$\n?", re.S | re.M | re.I)
RAW_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*raw\b.*?^[ \t]*\1[ \t]*$\n?", re.S | re.M | re.I)


# ---------------------------------------------------------------- render


def pick_labels(template_labels: dict | None, user_labels: dict | None, loc: Locale) -> dict:
    """Template labels per language ({en: {...}, pt: {...}}), overridable by the document."""
    out: dict = {}
    for src in (template_labels or {}, user_labels or {}):
        if not isinstance(src, dict):
            continue
        flat = {k: v for k, v in src.items() if not isinstance(v, dict)}
        out.update(src.get("en", {}) if isinstance(src.get("en"), dict) else {})
        lang = src.get(loc.language)
        if isinstance(lang, dict):
            out.update(lang)
        full = src.get(str(loc).replace("_", "-"))
        if isinstance(full, dict):
            out.update(full)
        out.update(flat)
    return out


def resolve_tz(meta: dict) -> ZoneInfo:
    from .locales import system_zone

    for name in (meta.get("timezone"), system_zone()):
        if name:
            try:
                return ZoneInfo(str(name).lstrip(":"))
            except Exception:  # noqa: BLE001
                pass
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def current_time(tz) -> datetime:
    import os

    if v := os.environ.get("BOBINA_NOW"):  # tests and reproducible previews
        return datetime.fromisoformat(v).replace(tzinfo=tz)
    return datetime.now(tz)


def _given_names(fields: dict | None) -> list[str]:
    """The names a {{ … }} could have used: data columns and --set keys (a joined source as a.column)."""
    out = []
    for k, v in (fields or {}).items():
        from .datasource import internal

        if internal(k) or (k == "row" and isinstance(v, dict)):  # bobina's own keys; row['Exact Name']
            continue
        if isinstance(v, dict):
            out += [f"{k}.{c}" for c in v]
        else:
            out.append(str(k))
    return out


def render(
    body: str,
    meta: dict,
    nudges: Nudges,
    fields: dict | None = None,
    counters: CounterStore | None = None,
    line_offset: int = 0,
    defaults: dict | None = None,
    labels: dict | None = None,
    quiet_names: frozenset = frozenset(),
    locale=None,
) -> Rendered:
    """locale: the document's locales.Choice (engine.build makes it); None: the document's locale: or English."""
    from .locales import choose

    choice = locale or choose(meta)
    loc, tz = choice.locale, resolve_tz(meta)
    values: list[Value] = []
    undefined_names: list[str] = []
    budget = Budget(seconds=MAX_SECONDS)
    store = counters or CounterStore(meta.get("counters"), nudges)

    class RecUndefined(ChainableUndefined):  # {{ c.id }} / {{ row["x"] }} on something undefined: M130, not a crash
        def __str__(self):
            if self._undefined_exception is JinjaSecurityError:
                self._fail_with_undefined_error()
            undefined_names.append(self._undefined_name or "?")
            return ""

    lengths: list[int] = []  # of each value once its placeholders are resolved (they nest: {% set %} blocks)

    def resolved_len(text: str) -> int:
        """What text becomes in the document: a placeholder counts as its value, not as its few characters."""
        n = len(text)
        if PH_OPEN in text:
            for m in PH_RE.finditer(text):
                i = int(m.group(1))
                n += (lengths[i] if i < len(lengths) else 0) - len(m.group(0))
        return n

    def finalize(v):
        if isinstance(v, MdSafe):
            return str(v)
        if isinstance(v, Undefined):
            str(v)
            return ""
        if v is None:
            return ""
        text = str(v)
        lengths.append(resolved_len(text))
        values.append(Value(text, isinstance(v, Tainted)))
        return f"{PH_OPEN}{len(values) - 1}{PH_CLOSE}"

    env = Sandbox(
        budget,
        Budget(MAX_CALLS, "macro calls"),
        finalize=finalize,
        undefined=RecUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        comment_start_string="<#",
        comment_end_string="#>",  # `{#id}` stays a Pandoc attribute
    )
    env.filters.update(make_filters(loc, tz, nudges, choice.explicit))
    for name, f in list(env.filters.items()):  # built-in and ours: a filter never turns data into document
        if name != "markdown":  # markdown already handles data (no images, no raw) and returns MdSafe
            f = keep_taint(f)
        env.filters[name] = _size_guard(name, f, env)

    def safe_range(*args):
        return SafeRange(range(*args), budget)

    now = current_time(tz)
    ctx = {k: v for k, v in meta.items() if k not in RESERVED}
    ctx.update(fields or {})
    ctx.update(
        {
            "now": now,
            "today": now.date(),
            "seq": Seq(store, budget),
            "range": safe_range,
            "namespace": _BudgetNamespace,
            "label": pick_labels(labels, meta.get("labels"), loc),
        }
    )
    env.globals.clear()
    for k, d in (defaults or {}).items():
        if k not in ctx or ctx[k] in (None, ""):
            try:
                ctx[k] = MdSafe(env.from_string(str(d)).render(ctx)) if "{{" in str(d) else d
            except SecurityError:
                raise
            except Exception as e:  # noqa: BLE001
                raise ValueError(f"default of field '{k}': {e}") from e

    try:
        tpl = env.from_string(body)
        out, size = [], 0
        for chunk in tpl.generate(ctx):
            size += resolved_len(chunk)  # {{ b }} 1000 times is 1000 times b, whatever the placeholders weigh
            if size > MAX_OUTPUT:
                raise SecurityError("M313", "document grew beyond 2 MB while rendering")
            out.append(chunk)
    except TemplateSyntaxError as e:
        raise ValueError(f"line {e.lineno + line_offset}: template syntax error: {e.message}") from e
    except JinjaSecurityError as e:
        raise SecurityError("M311", f"unsafe template operation: {e}") from e
    except RecursionError:
        raise SecurityError("M313", "a macro or a recursive loop calls itself too deeply") from None
    except MemoryError:
        raise SecurityError("M313", "the template needs more memory than any document") from None
    except UndefinedError as e:  # {{ lipsum() }}: calling something that is not defined
        raise ValueError(f"template error: {e.message}") from None
    except ArithmeticError as e:  # {{ 1 / 0 }}, {{ 10.0 ** 400 }}
        raise ValueError(f"template error: {e}") from None
    except TypeError as e:
        if "no loader" in str(e):
            raise SecurityError("M310", "templates cannot read files (include/import are disabled)") from e
        raise ValueError(f"template error: {e}") from e

    given = _given_names(fields)
    for name in dict.fromkeys(undefined_names):
        if name in quiet_names:  # already reported as an empty required field (M131): one cause, one warning
            continue
        hint = "set it in front matter, --set or --data"
        if given:
            hint += "; the data and --set give: " + ", ".join(given[:12]) + (" …" if len(given) > 12 else "")
        nudges.add("M130", f"variable '{name}' is not defined", suggestion=hint)
    return Rendered("".join(out), values, store, _data_texts(fields))
