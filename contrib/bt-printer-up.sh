#!/usr/bin/env bash
# Keeps Bluetooth on and the printer paired. Runs at boot (systemd --user, see install.sh).
#
#   bt-printer-up.sh           power on BT, unblock rfkill, pair if needed
#   bt-printer-up.sh --probe   ...and test an RFCOMM connection
#
# The printer address comes from bobina's config (bobina printer add NAME ADDRESS),
# or from PRINTER_MAC. PIN: PRINTER_PIN (default 0000).
set -u
log() { echo "[bt-printer] $*"; }
BOBINA="${BOBINA:-$HOME/.local/bin/bobina}"
MAC="${PRINTER_MAC:-}"
if [ -z "$MAC" ] && [ -x "$BOBINA" ]; then
  MAC="$("$BOBINA" printer list --json 2>/dev/null | python3 -c 'import json,sys
d = json.load(sys.stdin); p = d.get("printers", {}).get(d.get("default") or "", {})
print(p.get("address", "") if p.get("transport", "bluetooth") == "bluetooth" else "")' 2>/dev/null)"
fi
[ -z "$MAC" ] && { log "no Bluetooth printer configured (bobina printer add NAME ADDRESS)"; exit 0; }
PIN="${PRINTER_PIN:-0000}"

# 1. wait for bluetoothd and the adapter (boot)
for _ in $(seq 1 30); do
  bluetoothctl show 2>/dev/null | grep -q "^Controller" && break
  sleep 2
done
bluetoothctl show 2>/dev/null | grep -q "^Controller" || { log "no Bluetooth adapter"; exit 1; }

# 2. unblock rfkill (soft) without sudo: /dev/rfkill is rw for group netdev
if grep -qx 1 /sys/class/rfkill/rfkill*/soft 2>/dev/null; then
  python3 -c 'import os,struct; fd=os.open("/dev/rfkill",os.O_WRONLY); os.write(fd,struct.pack("IBBBB",0,0,2,0,0)); os.close(fd)' \
    && log "rfkill unblocked" || log "could not unblock rfkill"
  sleep 1
fi

# 3. power on the adapter
for _ in $(seq 1 10); do
  bluetoothctl show | grep -q "Powered: yes" && break
  bluetoothctl power on >/dev/null 2>&1
  sleep 2
done
bluetoothctl show | grep -q "Powered: yes" && log "adapter on" || { log "adapter did not power on"; exit 1; }

# 4. pair + trust if not paired yet
if bluetoothctl info "$MAC" 2>/dev/null | grep -q "Paired: yes"; then
  log "printer $MAC already paired"
else
  log "pairing $MAC (the printer must be on)..."
  { echo "agent KeyboardOnly"; echo "default-agent"; echo "scan on"; sleep 15
    echo "pair $MAC"; sleep 8; echo "$PIN"; sleep 8
    echo "trust $MAC"; sleep 2; echo "scan off"; echo quit; } | bluetoothctl >/dev/null 2>&1
  if bluetoothctl info "$MAC" 2>/dev/null | grep -q "Paired: yes"; then
    log "paired"
  else
    log "not paired (printer off or out of range?)"
    exit 0   # not a boot error: the next print retries
  fi
fi
bluetoothctl trust "$MAC" >/dev/null 2>&1

# 5. (optional) test the connection
if [ "${1:-}" = "--probe" ]; then
  if python3 -c "
import socket; s=socket.socket(socket.AF_BLUETOOTH,socket.SOCK_STREAM,socket.BTPROTO_RFCOMM)
s.settimeout(10); s.connect(('$MAC',1)); s.close()" 2>/dev/null; then
    log "RFCOMM connection ok"
  else
    log "could not connect (printer off or asleep?)"; exit 2
  fi
fi
