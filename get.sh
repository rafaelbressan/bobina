#!/bin/sh
# Installs bobina from PyPI, without a checkout:
#
#   curl -LsSf https://raw.githubusercontent.com/rafaelbressan/bobina/main/get.sh | sh
#   curl -LsSf https://raw.githubusercontent.com/rafaelbressan/bobina/main/get.sh | sh -s -- --bluetooth-service
#
# It installs uv (https://docs.astral.sh/uv/, with its official installer) when missing, then runs
# `uv tool install bobina`; running it again upgrades and keeps the extras installed before. Options: usage()
# below or docs/INSTALL.md. From a checkout, developers use ./install.sh (editable). POSIX sh (dash, busybox,
# macOS sh). Everything runs from main, called on the last line: a download cut short runs nothing.
set -eu

REPO_RAW="https://raw.githubusercontent.com/rafaelbressan/bobina"
# Pythons tried for Bluetooth sockets, in order (install.sh has the same list)
PYTHON_CANDIDATES="/usr/bin/python3 python3 python3.14 python3.13 python3.12 python3.11"
TMP=""

say() { printf '%s\n' "bobina: $*"; }
warn() { printf '%s\n' "bobina: warning: $*" >&2; }
die() { printf '%s\n' "bobina: error: $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Installs bobina from PyPI with uv (installing uv first when it is missing). Running it again upgrades.

  sh get.sh [--version V] [--extras LIST] [--python PATH] [--bluetooth-service]

  --version V          that version (default: the latest release; 0.2.0rc1 for a pre-release)
  --extras LIST        optional parts, comma-separated: pdf, svg, xlsx, mcp (PDF pages, SVG images, .xlsx data,
                       the bobina mcp server for agents). Default: the extras installed before, if any
  --python PATH        the Python to install with (default on Linux: a system Python 3.11+ with Bluetooth sockets)
  --bluetooth-service  Linux: also the systemd user service that keeps Bluetooth on and the printer paired
EOF
}

cleanup() { [ -z "$TMP" ] || rm -rf "$TMP"; }

fetch() {  # fetch URL FILE
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$2" "$1"
  else
    die "needs curl or wget"
  fi
}

find_uv() {
  for c in "$(command -v uv 2>/dev/null || true)" "${UV_INSTALL_DIR:-}/uv" "${XDG_BIN_HOME:-}/uv" \
    "$HOME/.local/bin/uv" "${CARGO_HOME:-$HOME/.cargo}/bin/uv"; do
    case "$c" in /*) [ -x "$c" ] && { printf '%s\n' "$c"; return 0; } ;; esac
  done
  return 1
}

# uv's own Pythons (and Homebrew's) are built without socket.AF_BLUETOOTH, which bobina needs for Bluetooth
# printers; Linux distributions' Pythons have it. Prints the first candidate that is 3.11+ and has it.
bluetooth_python() {
  for c in $PYTHON_CANDIDATES; do
    p="$(command -v "$c" 2>/dev/null || true)"
    [ -n "$p" ] || continue
    if "$p" -c 'import socket, sys; sys.exit(not (sys.version_info >= (3, 11) and hasattr(socket, "AF_BLUETOOTH")))' \
      2>/dev/null; then
      printf '%s\n' "$p"
      return 0
    fi
  done
  return 1
}

systemd_quote() {  # a value for a systemd unit, in double quotes: \ and " escaped, % doubled
  printf '"%s"' "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/%/%%/g')"
}

install_service() {  # install_service BOBINA VERSION
  if [ "$(uname -s)" != Linux ] || ! command -v systemctl >/dev/null 2>&1 || ! command -v bluetoothctl >/dev/null 2>&1
  then
    warn "--bluetooth-service needs Linux with systemd and bluetoothctl (BlueZ); skipped"
    return 0
  fi
  case "$2" in  # the tag of a version: 0.1.0 -> v0.1.0, 0.2.0rc1 -> v0.2.0-rc.1
    *rc*) tag="v${2%%rc*}-rc.${2##*rc}" ;;
    *) tag="v$2" ;;
  esac
  for f in bt-printer-up.sh systemd/bt-printer.service; do
    fetch "$REPO_RAW/$tag/contrib/$f" "$TMP/${f##*/}" || die "could not download contrib/$f of $tag from $REPO_RAW"
  done
  data="${XDG_DATA_HOME:-$HOME/.local/share}/bobina"
  unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/bt-printer.service"
  mkdir -p "$data/contrib" "$(dirname "$unit")"
  cp "$TMP/bt-printer-up.sh" "$data/contrib/bt-printer-up.sh"
  chmod +x "$data/contrib/bt-printer-up.sh"
  # The unit runs the script from $data and tells it where bobina is (it looks in ~/.local/bin otherwise). The
  # paths are quoted for systemd, never substituted into the template text. The script is an argument of env:
  # systemd refuses an executable path with spaces or $, and expands $ in arguments (hence $$).
  exec_start="/usr/bin/env bash $(systemd_quote "$data/contrib/bt-printer-up.sh" | sed 's/\$/$$/g')"
  environment="$(systemd_quote "BOBINA=$1")"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ExecStart=@BOBINA_REPO@/contrib/bt-printer-up.sh) printf 'ExecStart=%s\n' "$exec_start" ;;
      *@BOBINA_REPO@*) die "contrib/systemd/bt-printer.service of $tag has a line this script does not know: $line" ;;
      *) printf '%s\n' "$line" ;;
    esac
    if [ "$line" = "[Service]" ]; then printf 'Environment=%s\n' "$environment"; fi
  done < "$TMP/bt-printer.service" > "$TMP/unit"
  mv "$TMP/unit" "$unit"
  systemctl --user daemon-reload
  systemctl --user enable bt-printer.service >/dev/null
  say "boot service: bt-printer.service enabled ($unit)"
  loginctl show-user "$(id -un)" -p Linger 2>/dev/null | grep -q yes ||
    say "note: no linger; for the service at boot without a login: sudo loginctl enable-linger $(id -un)"
}

main() {
  version="" extras="" extras_given=no python="${BOBINA_PYTHON:-}" service=no
  while [ $# -gt 0 ]; do
    case "$1" in
      --version) [ $# -ge 2 ] || die "--version needs a value"; version="$2"; shift 2 ;;
      --version=*) version="${1#*=}"; shift ;;
      --extras) [ $# -ge 2 ] || die "--extras needs a list (pdf,svg,xlsx,mcp)"; extras="$2"; extras_given=yes; shift 2 ;;
      --extras=*) extras="${1#*=}"; extras_given=yes; shift ;;
      --python) [ $# -ge 2 ] || die "--python needs a path"; python="$2"; shift 2 ;;
      --python=*) python="${1#*=}"; shift ;;
      --bluetooth-service) service=yes; shift ;;
      -h | --help) usage; exit 0 ;;
      *) die "unknown option: $1 (see --help)" ;;
    esac
  done

  TMP="$(mktemp -d 2>/dev/null || mktemp -d -t bobina)"

  # 1. uv
  uv="$(find_uv || true)"
  if [ -z "$uv" ]; then
    say "installing uv (https://astral.sh/uv/install.sh)"
    fetch https://astral.sh/uv/install.sh "$TMP/uv-install.sh"
    sh "$TMP/uv-install.sh" || die "the uv installer failed; install uv (https://docs.astral.sh/uv/) and run this again"
    uv="$(find_uv || true)"
    [ -n "$uv" ] || die "uv was installed but not found; open a new terminal and run this again"
  fi

  # 2. a Python with Bluetooth sockets (Linux only: other systems have none to find)
  if [ -z "$python" ] && [ "$(uname -s)" = Linux ]; then
    python="$(bluetooth_python || true)"
    [ -n "$python" ] || warn "no system Python 3.11+ with Bluetooth sockets; uv's own Python will be used, and" \
      "it cannot reach Bluetooth printers (file and command printers work). Install python3.11 or newer from your" \
      "distribution (Ubuntu 22.04: sudo apt install python3.11) and run this again."
  fi

  # 3. bobina, keeping the extras of an earlier install unless --extras says otherwise
  if [ "$extras_given" = no ]; then
    extras="$("$uv" tool list --show-extras 2>/dev/null |
      sed -n 's/^bobina v[^ ]* \[extras: \([^]]*\)\].*/\1/p' | tr -d ' ')" || extras=""
    [ -z "$extras" ] || say "keeping the extras installed before: $extras"
  fi
  spec="bobina${extras:+[$extras]}${version:+==$version}"
  say "uv tool install $spec${python:+ (Python: $python)}"
  set -- tool install --upgrade
  [ -z "$python" ] || set -- "$@" --python "$python"
  "$uv" "$@" "$spec" ||
    die "uv tool install failed. Installed with pipx before? Run: pipx uninstall bobina, then this again"
  bin="$("$uv" tool dir --bin)"
  [ -x "$bin/bobina" ] || die "bobina is not in $bin after the install"
  installed="$("$bin/bobina" --version | awk '{print $NF}')"
  say "installed bobina $installed in $bin"

  # 4. the Bluetooth service (optional), from the tag of the installed version
  [ "$service" = no ] || install_service "$bin/bobina" "$installed"

  case ":$PATH:" in
    *":$bin:"*) ;;
    *) say "note: $bin is not in PATH; run: $uv tool update-shell   (then open a new terminal)" ;;
  esac
  cat <<'EOF'

Next:
  bobina printer scan                     find the printer's Bluetooth address
  bobina printer add NAME ADDRESS         e.g. bobina printer add mtp AA:BB:CC:DD:EE:FF
  bobina status                           paper, cover, errors
  bobina print "# hello" --yes            the first ticket

No printer at hand? bobina printer add test --path out.bin (a file printer). Help: bobina help
EOF
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
main "$@" </dev/null
