#!/bin/sh
# Installs bobina from PyPI, without a checkout:
#
#   curl -LsSf https://raw.githubusercontent.com/rafaelbressan/bobina/main/get.sh | sh
#   curl -LsSf https://raw.githubusercontent.com/rafaelbressan/bobina/main/get.sh | sh -s -- --bluetooth-service
#
# It installs uv (https://docs.astral.sh/uv/, with its official installer) when missing, then runs
# `uv tool install bobina`; running it again upgrades. Options: see usage() below or docs/INSTALL.md.
# From a checkout, developers use ./install.sh (editable) instead. POSIX sh (dash, busybox, macOS sh).
set -eu

REPO_RAW="https://raw.githubusercontent.com/rafaelbressan/bobina"
VERSION=""
EXTRAS=""
PYTHON="${BOBINA_PYTHON:-}"
SERVICE=no

say() { printf '%s\n' "bobina: $*"; }
warn() { printf '%s\n' "bobina: warning: $*" >&2; }
die() { printf '%s\n' "bobina: error: $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Installs bobina from PyPI with uv (installing uv first when it is missing). Running it again upgrades.

  sh get.sh [--version V] [--extras LIST] [--python PATH] [--bluetooth-service]

  --version V          that version (default: the latest release; 0.2.0rc1 for a pre-release)
  --extras LIST        optional parts, comma-separated: pdf, svg, xlsx (PDF pages, SVG images, .xlsx data)
  --python PATH        the Python to install with (default on Linux: a system Python 3.11+ with Bluetooth sockets)
  --bluetooth-service  Linux: also the systemd user service that keeps Bluetooth on and the printer paired
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --version) [ $# -ge 2 ] || die "--version needs a value"; VERSION="$2"; shift 2 ;;
    --version=*) VERSION="${1#*=}"; shift ;;
    --extras) [ $# -ge 2 ] || die "--extras needs a list (pdf,svg,xlsx)"; EXTRAS="$2"; shift 2 ;;
    --extras=*) EXTRAS="${1#*=}"; shift ;;
    --python) [ $# -ge 2 ] || die "--python needs a path"; PYTHON="$2"; shift 2 ;;
    --python=*) PYTHON="${1#*=}"; shift ;;
    --bluetooth-service) SERVICE=yes; shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

fetch() {  # fetch URL FILE
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --retry 3 "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$2" "$1"
  else
    die "needs curl or wget"
  fi
}

TMP="$(mktemp -d 2>/dev/null || mktemp -d -t bobina)"
trap 'rm -rf "$TMP"' EXIT INT TERM

# 1. uv
find_uv() {
  for c in "$(command -v uv 2>/dev/null || true)" "${UV_INSTALL_DIR:-}/uv" "${XDG_BIN_HOME:-}/uv" \
    "$HOME/.local/bin/uv" "${CARGO_HOME:-$HOME/.cargo}/bin/uv"; do
    case "$c" in /*) [ -x "$c" ] && { printf '%s\n' "$c"; return 0; } ;; esac
  done
  return 1
}
UV="$(find_uv || true)"
if [ -z "$UV" ]; then
  say "installing uv (https://astral.sh/uv/install.sh)"
  fetch https://astral.sh/uv/install.sh "$TMP/uv-install.sh"
  sh "$TMP/uv-install.sh" || die "the uv installer failed; install uv (https://docs.astral.sh/uv/) and run this again"
  UV="$(find_uv || true)"
  [ -n "$UV" ] || die "uv was installed but not found; open a new terminal and run this again"
fi

# 2. a Python with Bluetooth sockets. uv's own Pythons are built without them, so on Linux a system Python
# 3.11+ that has them is used when there is one (bobina reaches Bluetooth printers through AF_BLUETOOTH).
has_bluetooth() {
  "$1" -c 'import socket, sys; sys.exit(not (sys.version_info >= (3, 11) and hasattr(socket, "AF_BLUETOOTH")))' \
    2>/dev/null
}
if [ -z "$PYTHON" ] && [ "$(uname -s)" = Linux ]; then
  for c in /usr/bin/python3 python3 python3.14 python3.13 python3.12 python3.11; do
    p="$(command -v "$c" 2>/dev/null || true)"
    if [ -n "$p" ] && has_bluetooth "$p"; then PYTHON="$p"; break; fi
  done
  [ -n "$PYTHON" ] || warn "no system Python 3.11+ with Bluetooth sockets; uv's own Python will be used, and" \
    "it cannot reach Bluetooth printers (file and command printers work). Install python3.11 or newer from your" \
    "distribution (Ubuntu 22.04: sudo apt install python3.11) and run this again."
fi

# 3. bobina
spec="bobina${EXTRAS:+[$EXTRAS]}${VERSION:+==$VERSION}"
say "uv tool install $spec${PYTHON:+ (Python: $PYTHON)}"
if [ -n "$PYTHON" ]; then
  "$UV" tool install --upgrade --python "$PYTHON" "$spec" ||
    die "uv tool install failed. Installed with pipx before? Run: pipx uninstall bobina, then this again"
else
  "$UV" tool install --upgrade "$spec" ||
    die "uv tool install failed. Installed with pipx before? Run: pipx uninstall bobina, then this again"
fi
BIN="$("$UV" tool dir --bin)"
BOBINA="$BIN/bobina"
[ -x "$BOBINA" ] || die "bobina is not in $BIN after the install"
INSTALLED="$("$BOBINA" --version | awk '{print $NF}')"
say "installed bobina $INSTALLED in $BIN"

# 4. the Bluetooth service (optional), from the tag of the installed version
if [ "$SERVICE" = yes ]; then
  if [ "$(uname -s)" != Linux ] || ! command -v systemctl >/dev/null 2>&1 || ! command -v bluetoothctl >/dev/null 2>&1
  then
    warn "--bluetooth-service needs Linux with systemd and bluetoothctl (BlueZ); skipped"
  else
    case "$INSTALLED" in  # the tag of a version: 0.1.0 -> v0.1.0, 0.2.0rc1 -> v0.2.0-rc.1
      *rc*) tag="v${INSTALLED%%rc*}-rc.${INSTALLED##*rc}" ;;
      *) tag="v$INSTALLED" ;;
    esac
    data="${XDG_DATA_HOME:-$HOME/.local/share}/bobina"
    unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/bt-printer.service"
    for f in bt-printer-up.sh systemd/bt-printer.service; do
      fetch "$REPO_RAW/$tag/contrib/$f" "$TMP/${f##*/}" || die "could not download contrib/$f of $tag from $REPO_RAW"
    done
    mkdir -p "$data/contrib" "$(dirname "$unit")"
    cp "$TMP/bt-printer-up.sh" "$data/contrib/bt-printer-up.sh"
    chmod +x "$data/contrib/bt-printer-up.sh"
    # the unit runs the script from $data and tells it where bobina is (it looks in ~/.local/bin otherwise)
    awk -v d="$data" -v b="$BOBINA" '{ gsub("@BOBINA_REPO@", d); print } /^\[Service\]/ { print "Environment=BOBINA=" b }' \
      "$TMP/bt-printer.service" > "$unit"
    systemctl --user daemon-reload
    systemctl --user enable bt-printer.service >/dev/null
    say "boot service: bt-printer.service enabled ($unit)"
    loginctl show-user "$(id -un)" -p Linger 2>/dev/null | grep -q yes ||
      say "note: no linger; for the service at boot without a login: sudo loginctl enable-linger $(id -un)"
  fi
fi

case ":$PATH:" in
  *":$BIN:"*) ;;
  *) say "note: $BIN is not in PATH; run: $UV tool update-shell   (then open a new terminal)" ;;
esac
cat <<EOF

Next:
  bobina printer scan                     find the printer's Bluetooth address
  bobina printer add NAME ADDRESS         e.g. bobina printer add mtp AA:BB:CC:DD:EE:FF
  bobina status                           paper, cover, errors
  bobina print "# hello" --yes            the first ticket

No printer at hand? bobina printer add test --path out.bin (a file printer). Help: bobina help
EOF
