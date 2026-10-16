#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo '请使用 sudo sh ./install.sh。' >&2; exit 1; }
[ "$(uname -s)" = Linux ] || { echo '需要使用 systemd 的 Linux。' >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo '请先安装 Python 3.9 或更新版本。' >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo '需要 Python 3.9 或更新版本。' >&2; exit 1; }
command -v systemctl >/dev/null 2>&1 || { echo '需要系统已有 systemd。' >&2; exit 1; }
sha256sum -c SHA256SUMS
. /etc/os-release
if [ "$ID" = debian ] && command -v dpkg >/dev/null 2>&1; then
    selected="dependencies/debian${VERSION_ID}-$(dpkg --print-architecture).tar.gz"
    if [ -f "$selected" ]; then
        echo "自动选择：Debian $VERSION_ID / $(dpkg --print-architecture)；仅补齐缺失依赖。"
        temporary=$(mktemp -d)
        trap 'rm -rf "$temporary"' EXIT HUP INT TERM
        tar -xzf "$selected" -C "$temporary"
        sh "$temporary"/campus-network_*/install.sh
        exit 0
    fi
fi
# Other distributions use their installed dependencies and native package manager.
for tool in curl systemctl ip; do
    command -v "$tool" >/dev/null 2>&1 || { echo "当前系统不含离线依赖，请先安装 $tool。" >&2; exit 1; }
done
if command -v dpkg >/dev/null 2>&1; then
    dpkg --force-confold -i packages/*.deb
elif command -v rpm >/dev/null 2>&1; then
    rpm -Uvh packages/*.rpm
else
    sh ./install-runtime.sh
fi
