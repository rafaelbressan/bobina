"""The Bluetooth link stays open until the job has left the computer and the printer confirms it.

The kernel send buffer of an RFCOMM socket holds ~50 KB: sendall() of a 29 KB raster returns at once and the bytes
then cross at the speed the printer prints. Closing early dropped what was still queued (08/11: the end of a strip
and its final feed). The wait follows the queue in the kernel, not an estimated rate."""

from bobina import transport
from bobina.profile import load


class Clock:
    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeSocket:
    def __init__(self, events):
        self.events, self.timeouts = events, []
        self.linger = None

    def settimeout(self, t):
        self.timeouts.append(t)

    def sendall(self, b):
        self.events.append(("send", b))

    def recv(self, n):
        self.events.append(("recv", None))
        return b"\x00"

    def setsockopt(self, level, opt, value):
        self.linger = value

    def close(self):
        self.events.append(("close", None))


def _send(monkeypatch, data, queue, length_mm=85):
    """queue: what the kernel reports as still unsent on each look (the last value repeats); None = unknown."""
    events, clock, notes = [], Clock(), []
    sock = FakeSocket(events)
    looks = iter(queue)
    last = [None]

    def unsent(s):
        last[0] = next(looks, last[0])
        events.append(("queue", last[0]))
        return last[0]

    monkeypatch.setattr(transport, "_bt_connect", lambda mac, ch, *a: sock)
    monkeypatch.setattr(transport, "_unsent", unsent)
    monkeypatch.setattr(transport.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(transport.time, "sleep", clock.sleep)
    printer = {"transport": "bluetooth", "address": "AA:BB:CC:DD:EE:FF"}
    transport.send(data, printer, load("mtp-ii-58"), log=lambda *a, **k: notes.append(a[0]), length_mm=length_mm)
    return events, clock, notes, sock


def test_the_status_request_goes_out_only_after_the_queue_drained(monkeypatch):
    events, clock, notes, _ = _send(monkeypatch, b"\x00" * 28_891, [28_000, 20_000, 9_000, 0])
    sends = [v for e, v in events if e == "send"]
    assert sends[-1] == b"\x1dr\x01"
    drained_at = next(i for i, (e, v) in enumerate(events) if e == "queue" and v == 0)
    status_at = next(i for i, (e, v) in enumerate(events) if e == "send" and v == b"\x1dr\x01")
    assert drained_at < status_at
    assert not notes  # confirmed: nothing to warn about


def test_a_slow_queue_is_waited_for_as_long_as_it_moves(monkeypatch):
    slow = list(range(28_000, 0, -100)) + [0]  # 280 looks: far longer than any rate estimate allowed
    events, clock, notes, _ = _send(monkeypatch, b"\x00" * 28_891, slow)
    assert ("queue", 0) in events and not notes


def test_a_stalled_queue_is_a_partial_send_not_a_print(monkeypatch):
    import pytest

    with pytest.raises(transport.SendFailed) as e:  # "printed on …" would be a lie: the printer stopped taking it
        _send(monkeypatch, b"\x00" * 28_891, [5_000])  # never moves
    assert e.value.sent == 28_891 - 5_000 and "stopped taking" in str(e.value)
    assert transport.time.monotonic() < 120  # gave up after STALL_S without progress, not MAX_DRAIN_S


def test_unknown_queue_falls_back_to_the_paper_time(monkeypatch):
    events, clock, notes, _ = _send(monkeypatch, b"x" * 45, [None], length_mm=15)
    assert ("recv", None) in events and clock.t < 15


def test_the_socket_lingers_on_close(monkeypatch):
    *_, sock = _send(monkeypatch, b"x" * 45, [0], length_mm=15)
    assert sock.linger is not None  # close() waits for anything still queued instead of dropping it


def _raster(rows):
    return b"\x1dv0\x00" + bytes([48, 0, rows, 0]) + b"\x00" * (48 * rows)


def test_split_tail_finds_the_commands_after_the_last_raster_block():
    head = b"\x1b@\x1bJ\x18" + _raster(64) + _raster(24)
    assert transport._split_tail(head + b"\x1bJ8") == (head, b"\x1bJ8")
    assert transport._split_tail(b"\x1b@hello\n\x1bJ8") == (b"\x1b@hello\n\x1bJ8", b"")  # no raster: no split
    assert transport._split_tail(head) == (head, b"")  # nothing after the image
    text_after = head + b"a long native text after the image\n" * 4
    assert transport._split_tail(text_after) == (text_after, b"")  # more than a few commands: not a tail


class BusySocket(FakeSocket):
    """Drops status requests while 'printing' (the MTP-II does): the first `busy` asks time out."""

    def __init__(self, events, busy):
        super().__init__(events)
        self.busy = busy

    def recv(self, n):
        self.events.append(("recv", None))
        if self.busy:
            self.busy -= 1
            raise TimeoutError
        return b"\x00"


def test_the_final_feed_waits_until_the_printer_finished_the_image(monkeypatch):
    events, clock, notes = [], Clock(), []
    sock = BusySocket(events, busy=3)
    monkeypatch.setattr(transport, "_bt_connect", lambda mac, ch, *a: sock)
    monkeypatch.setattr(transport, "_unsent", lambda s: 0)
    monkeypatch.setattr(transport.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(transport.time, "sleep", clock.sleep)
    job = b"\x1b@" + _raster(64) * 3 + b"\x1bJ8"
    printer = {"transport": "bluetooth", "address": "AA:BB:CC:DD:EE:FF"}
    transport.send(job, printer, load("mtp-ii-58"), log=lambda *a, **k: notes.append(a[0]), length_mm=24)
    sends = [v for e, v in events if e == "send"]
    feed_at = sends.index(b"\x1bJ8")
    assert sends[:feed_at].count(b"\x1dr\x01") == 4  # 3 dropped while printing, the 4th answered: idle
    assert sends[-1] == b"\x1dr\x01" and not notes  # then the feed, then the confirmation


class Profile(dict):
    """mtp-ii-58 with some keys replaced."""

    def __init__(self, **over):
        super().__init__()
        self.over, self.base = over, load("mtp-ii-58")

    def get(self, key, default=None):
        return self.over[key] if key in self.over else self.base.get(key, default)

    @property
    def id(self):
        return self.base.id


def _run(monkeypatch, sock, job, profile=None, unsent=lambda s: 0):
    clock, notes = Clock(), []
    monkeypatch.setattr(transport, "_bt_connect", lambda mac, ch, *a: sock)
    monkeypatch.setattr(transport, "_unsent", unsent)
    monkeypatch.setattr(transport.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(transport.time, "sleep", clock.sleep)
    printer = {"transport": "bluetooth", "address": "AA:BB:CC:DD:EE:FF"}
    transport.send(
        job,
        printer,
        profile if profile is not None else load("mtp-ii-58"),
        log=lambda *a, **k: notes.append(a[0]),
        length_mm=24,
    )
    return notes


IMAGE_JOB = b"\x1b@" + _raster(64) * 3 + b"\x1bJ8"


def test_only_profiles_that_ask_for_it_wait_before_the_tail(monkeypatch):
    events = []
    _run(monkeypatch, BusySocket(events, busy=0), IMAGE_JOB, Profile(**{"transport.idle_before_tail": False}))
    sends = [v for e, v in events if e == "send"]
    assert sends.count(b"\x1dr\x01") == 1  # only the final confirmation: no polling on other printers


def test_a_link_closed_while_printing_the_image_is_an_error(monkeypatch):
    import pytest

    class Closing(BusySocket):
        def recv(self, n):
            return b""

    with pytest.raises(transport.SendFailed):
        _run(monkeypatch, Closing([], busy=0), IMAGE_JOB)


def test_a_stuck_queue_does_not_send_the_tail_behind_it(monkeypatch):
    import pytest

    events = []
    with pytest.raises(transport.SendFailed):
        _run(monkeypatch, BusySocket(events, busy=0), IMAGE_JOB, unsent=lambda s: 5_000)
    assert b"\x1bJ8" not in [v for e, v in events if e == "send"]


def test_unsent_is_unknown_for_sockets_that_are_not_bluetooth():
    import socket

    a, b = socket.socketpair()
    try:
        assert transport._unsent(a) is None
    finally:
        a.close(), b.close()


def test_a_tear_mark_after_a_photo_is_part_of_the_tail():
    mark = b"\x1dv0\x00" + bytes([48, 0, 1, 0]) + b"\xf0" * 48  # --marks tear: a 1-row line inside the final feed
    photo = b"\x1b@" + _raster(64) * 3
    tail = b"\x1bJ0" + mark + b"\x1bJ'"
    assert transport._split_tail(photo + tail) == (photo, tail)  # the photo is the last image, not the mark


def test_a_printer_that_never_answers_gets_few_status_requests(monkeypatch):
    clock = Clock()

    class Silent(FakeSocket):
        def settimeout(self, t):
            self.t = t

        def recv(self, n):
            clock.sleep(self.t)  # the timeout passes
            raise TimeoutError

    events = []
    sock = Silent(events)
    monkeypatch.setattr(transport.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(transport.time, "sleep", clock.sleep)
    assert transport._wait_idle(sock, 30) is False
    asks = [v for e, v in events if e == "send"]
    assert len(asks) <= 10  # 0.5, 1, 2, 4, 4, 4 … s apart, not 60 requests in 30 s


def test_a_status_query_recovers_a_stuck_link_like_a_print(monkeypatch):
    import errno

    calls, ctl = [], []

    class Answering(FakeSocket):
        def recv(self, n):
            return b"\x16"

    def connect(mac, ch, *a):
        calls.append(mac)
        if len(calls) == 1:
            raise OSError(errno.EBUSY, "Device or resource busy")
        return Answering([])

    monkeypatch.setattr(transport, "_bt_connect", connect)
    monkeypatch.setattr(transport, "_bluetoothctl", lambda action, mac, t: ctl.append(action))
    monkeypatch.setattr(transport.time, "sleep", lambda s: None)
    assert transport.query("AA:BB:CC:DD:EE:FF", 1, [b"\x10\x04\x01"]) == [b"\x16"]
    assert "disconnect" in ctl  # the stale link left by a failed job is dropped, then asked again
