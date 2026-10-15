#!/bin/sh
# Run inside the matching Debian container; the resulting installer never downloads.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
[ "$(id -u)" -eq 0 ] || { echo '请在 root Debian 容器内运行。' >&2; exit 1; }
. /etc/os-release
[ "$ID" = debian ] || { echo '仅支持 Debian。' >&2; exit 1; }
case "$VERSION_ID" in 12|13) ;; *) echo '仅构建 Debian 12/13 离线包。' >&2; exit 1 ;; esac
version=$(cat VERSION)
architecture=$(dpkg --print-architecture)
package="dist/campus-network_${version}_all.deb"
[ -f "$package" ] || { echo "请先构建 $package。" >&2; exit 1; }
name="campus-network_${version}_debian${VERSION_ID}_${architecture}_offline"
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT HUP INT TERM
mkdir -p "$stage/$name/packages" "$stage/cache/partial"
chmod 0755 "$stage" "$stage/cache"
apt-get update
apt-get -y --download-only --no-install-recommends \
    -o Dir::State::status=/dev/null -o Dir::Cache::archives="$stage/cache" \
    install curl ca-certificates
cp "$stage/cache/"*.deb "$stage/$name/packages/"
cp "$package" "$stage/$name/packages/"
apt-get -y --no-install-recommends install apt-utils
(cd "$stage/$name" && apt-ftparchive packages packages > Packages)
cp README.md LICENSE "$stage/$name/"
cat > "$stage/$name/install.sh" <<'INSTALL'
#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo '请使用 sudo sh ./install.sh。' >&2; exit 1; }
. /etc/os-release
INSTALL
printf '%s\n' "[ \"\$ID\" = debian ] && [ \"\$VERSION_ID\" = '$VERSION_ID' ] && [ \"\$(dpkg --print-architecture)\" = '$architecture' ] || { echo '需要 Debian $VERSION_ID $architecture。' >&2; exit 1; }" >> "$stage/$name/install.sh"
cat >> "$stage/$name/install.sh" <<'INSTALL'
sha256sum -c SHA256SUMS
repository=$(mktemp -d /var/tmp/campus-network.XXXXXX)
trap 'rm -rf "$repository"' EXIT HUP INT TERM
chmod 0755 "$repository"
cp -a packages Packages "$repository/"
mkdir -p "$repository/lists/partial" "$repository/cache/partial"
cp packages/*.deb "$repository/cache/"
printf 'deb [trusted=yes] file:%s ./\n' "$repository" > "$repository/sources.list"
set -- -o "Dir::Etc::sourcelist=$repository/sources.list" \
    -o Dir::Etc::sourceparts=- -o "Dir::State::lists=$repository/lists" \
    -o "Dir::Cache::archives=$repository/cache" -o Acquire::Languages=none
apt-get "$@" update
apt-get "$@" --no-download --no-install-recommends -y \
    -o Dpkg::Options::=--force-confold install campus-network
INSTALL
chmod 0755 "$stage/$name/install.sh"
(cd "$stage/$name" && sha256sum Packages packages/*.deb > SHA256SUMS)
tar -C "$stage" -czf "dist/$name.tar.gz" "$name"
echo "dist/$name.tar.gz"
