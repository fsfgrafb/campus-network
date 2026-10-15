#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo '请使用 sudo sh ./install.sh（或切换到 root）。' >&2; exit 1; }
[ "$(uname -s)" = Linux ] || { echo '仅支持使用 systemd 的 Linux。' >&2; exit 1; }
for tool in python3 curl systemctl install; do
    command -v "$tool" >/dev/null 2>&1 || { echo "缺少 $tool；Debian 可使用对应版本的完整离线包。" >&2; exit 1; }
done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo '需要 Python 3.9 或更新版本。' >&2; exit 1; }
[ -d /run/systemd/system ] || { echo '需要以 systemd 作为系统服务管理器。' >&2; exit 1; }
if [ -f /usr/bin/campus-network ] && command -v dpkg-query >/dev/null 2>&1 && dpkg-query -S /usr/bin/campus-network >/dev/null 2>&1; then
    echo '检测到 Debian 包管理的安装，请使用 .deb 包升级。' >&2
    exit 1
fi
if [ -f /usr/bin/campus-network ] && command -v rpm >/dev/null 2>&1 && rpm -qf /usr/bin/campus-network >/dev/null 2>&1; then
    echo '检测到 RPM 包管理的安装，请使用 .rpm 包升级。' >&2
    exit 1
fi
systemctl stop campus-network.service 2>/dev/null || true
install -d -m 0755 /etc/campus-network /usr/lib/systemd/system /usr/share/bash-completion/completions /usr/share/doc/campus-network
install -d -m 0700 /var/lib/campus-network
install -m 0755 src/campus-network /usr/bin/campus-network
install -m 0644 systemd/campus-network.service /usr/lib/systemd/system/campus-network.service
install -m 0644 completion/campus-network /usr/share/bash-completion/completions/campus-network
install -m 0644 README.md LICENSE /usr/share/doc/campus-network/
if [ ! -f /etc/campus-network/config.json ]; then
    install -m 0644 config/config.json /etc/campus-network/config.json
fi
for file in /etc/campus-network/account /etc/campus-network/account.json; do
    if [ -f "$file" ]; then
        chown root:root "$file"
        chmod 0600 "$file"
    fi
done
systemctl daemon-reload
systemctl enable campus-network.service
systemctl restart campus-network.service
echo '安装完成。普通用户运行 campus-network on 首次配置；campus-network status 查看状态。'
