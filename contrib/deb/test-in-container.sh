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
    for i in 1 2 3 4 5; do apt-get update -qq --error-on=any && break; [ \$i = 5 ] && exit 1; sleep 15; done  # mirrors' DNS fails at times on CI
    apt-get install -y -qq --no-install-recommends /deb/$name >/dev/null
    python3 -c 'import socket, sys; print(sys.version, socket.AF_BLUETOOTH)'
    find /usr/lib/bobina/common/bobina -name '*.pyc' | grep -q .
    test -z \"\$(find /usr/lib/bobina -name direct_url.json)\"
    find /usr/lib/bobina -name '*.pyc' -delete
    dpkg-reconfigure python3  # python3 runs its runtime.d hooks, as on a new version: bobina's compiles again
    find /usr/lib/bobina/common/bobina -name '*.pyc' | grep -q .
    bob --version
    bobina --version
    bobina check 'hello from the .deb' --json
    bobina preview '# hello from the .deb' -o /tmp/hello.png
    test -s /tmp/hello.png
    apt-get remove -y -qq bobina >/dev/null
    test ! -e /usr/lib/bobina
"
