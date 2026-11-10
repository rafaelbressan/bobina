#!/usr/bin/env bash
# Installs bobina from this checkout (editable) and, on Linux with Bluetooth, the boot service
# that keeps the adapter on and the printer paired.
#
#   ./install.sh              install/upgrade bobina (+ bob) into ~/.local/bin
#   ./install.sh --no-service skip the systemd user service
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

UV="$(command -v uv || true)"; [ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
if [ -n "$UV" ]; then
  "$UV" tool install --force -e "$REPO"
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
