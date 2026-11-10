#!/bin/sh
# Install a bobina .deb in a clean container and run it, as a user would:
#   contrib/deb/test-in-container.sh debian:12 dist/bobina_0.1.0_amd64.deb
# Runs docker with --platform from the .deb's architecture (arm64 on an x86 machine needs QEMU/binfmt).
set -eu
image=$1
deb=$2
arch=$(dpkg-deb -f "$deb" Architecture)
dir=$(cd "$(dirname "$deb")" && pwd)
name=$(basename "$deb")
docker run --rm --platform "linux/$arch" -v "$dir:/deb:ro" "$image" sh -euxc "
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends /deb/$name >/dev/null
    python3 -c 'import socket, sys; print(sys.version, socket.AF_BLUETOOTH)'
    find /usr/lib/bobina/common/bobina -name '*.pyc' | grep -q .
    bobina --version
    bobina check 'hello from the .deb' --json
    bobina preview '# hello from the .deb' -o /tmp/hello.png
    test -s /tmp/hello.png
    apt-get remove -y -qq bobina >/dev/null
    test ! -e /usr/lib/bobina
"
