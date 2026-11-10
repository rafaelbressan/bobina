#!/usr/bin/env bash
# Installs bobina from this checkout (editable, for development) and, on Linux with Bluetooth, the boot service
# that keeps the adapter on and the printer paired. Without a checkout, get.sh installs the release from PyPI.
#
#   ./install.sh              install/upgrade bobina (+ bob) into ~/.local/bin
#   ./install.sh --no-service skip the systemd user service
[ -f "$(dirname "$0")/pyproject.toml" ] || {
  echo "install.sh installs a checkout; without one: curl -LsSf https://raw.githubusercontent.com/rafaelbressan/bobina/main/get.sh | sh" >&2
  exit 1
}
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# uv's own Pythons have no Bluetooth sockets: on Linux use a system Python 3.11+ that has them (see get.sh)
PY=""
for c in /usr/bin/python3 python3 python3.14 python3.13 python3.12 python3.11; do
  p="$(command -v "$c" 2>/dev/null || true)"
  if [ -n "$p" ] && "$p" -c 'import socket, sys; sys.exit(not (sys.version_info >= (3, 11) and hasattr(socket, "AF_BLUETOOTH")))' 2>/dev/null; then
    PY="$p"; break
  fi
done

UV="$(command -v uv || true)"; [ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
if [ -n "$UV" ]; then
  "$UV" tool install --force ${PY:+--python "$PY"} -e "$REPO"
elif command -v pipx >/dev/null; then
  pipx install --force -e "$REPO"
else
  echo "needs uv (https://docs.astral.sh/uv/) or pipx" >&2; exit 1
fi
chmod +x "$REPO"/contrib/*.sh

# legacy `imprimir` from the test phases now forwards to bobina print
if [ -e "$HOME/.local/bin/imprimir" ]; then
  cat > "$HOME/.local/bin/imprimir" <<'SH'
#!/usr/bin/env bash
echo "imprimir is now: bobina print   (see: bobina help)" >&2
exec "$HOME/.local/bin/bobina" print "$@"
SH
  chmod +x "$HOME/.local/bin/imprimir"
fi

if [ "${1:-}" != "--no-service" ] && command -v systemctl >/dev/null && command -v bluetoothctl >/dev/null; then
  unit="$HOME/.config/systemd/user/bt-printer.service"
  mkdir -p "$(dirname "$unit")"
  rm -f "$unit"   # older installs linked it from the repo root
  sed "s|@BOBINA_REPO@|$REPO|" "$REPO/contrib/systemd/bt-printer.service" > "$unit"
  systemctl --user daemon-reload
  systemctl --user enable bt-printer.service >/dev/null
  loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q yes || echo "note: no linger; for boot without login: sudo loginctl enable-linger $USER"
  echo "boot service: bt-printer.service enabled"
fi
echo "ok: $("$HOME/.local/bin/bobina" --version) — next: bobina printer scan; bobina printer add NAME ADDRESS"
