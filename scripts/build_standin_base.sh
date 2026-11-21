#!/bin/sh
# Build a LOCAL stand-in for python:3.11-slim from the host's python3.11 (Ubuntu/Debian host).
# Only needed where Docker Hub is unreachable (that was the case in the CI sandbox used to build
# this repository). With registry access, `docker build` pulls the real python:3.11-slim instead.
set -e
R=$(mktemp -d)
mkdir -p $R/bin $R/usr/local/bin $R/etc $R/tmp $R/root $R/var/tmp $R/proc $R/sys $R/dev
chmod 1777 $R/tmp $R/var/tmp
copy() { for b in "$@"; do [ -e "$b" ] || continue; mkdir -p "$R$(dirname "$b")"; cp -aL "$b" "$R$b"
  ldd "$b" 2>/dev/null | grep -o '/[^ ]*' | while read -r l; do mkdir -p "$R$(dirname "$l")"; cp -aL "$l" "$R$l" 2>/dev/null || true; done; done; }
copy /usr/bin/python3.11 /usr/bin/dash /usr/bin/find /usr/bin/chmod /usr/bin/chown /usr/bin/mkdir /usr/bin/rm \
     /usr/bin/cp /usr/bin/ls /usr/bin/cat /usr/bin/env /usr/bin/id /usr/bin/sleep /usr/sbin/useradd /usr/sbin/groupadd
cp -a /usr/lib/python3.11 $R/usr/lib/
for so in /usr/lib/python3.11/lib-dynload/*.so; do copy "$so"; done
for l in $(ldd /usr/bin/python3.11 | grep -o '/usr/local/lib/[^ ]*'); do cp -aL "$l" $R/usr/lib/x86_64-linux-gnu/; done
mkdir -p $R/usr/local/lib/python3.11/dist-packages
cp -a "$(python3.11 -c 'import pip,os;print(os.path.dirname(pip.__file__))')" $R/usr/local/lib/python3.11/dist-packages/
ln -sf /usr/bin/python3.11 $R/usr/local/bin/python
printf '#!/bin/sh\nexec /usr/bin/python3.11 -m pip "$@"\n' > $R/usr/local/bin/pip && chmod 755 $R/usr/local/bin/pip
ln -sf /usr/bin/dash $R/bin/sh
printf 'root:x:0:0:root:/root:/bin/sh\n' > $R/etc/passwd && printf 'root:x:0:\n' > $R/etc/group
printf 'root:*:19000:0:99999:7:::\n' > $R/etc/shadow && printf 'root:*::\n' > $R/etc/gshadow
cp /etc/login.defs /etc/nsswitch.conf $R/etc/ 2>/dev/null || true
(cd $R && tar -c .) | docker import --change 'ENV PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin' \
    --change 'ENV LANG=C.UTF-8' - python:3.11-slim
rm -rf "$R"
