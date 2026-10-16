#!/usr/bin/env python3
"""Build architecture-independent packages without downloading dependencies."""

import argparse
import gzip
import hashlib
import io
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / "VERSION").read_text().strip()
PAYLOAD = {
    "src/campus-network": ("usr/bin/campus-network", 0o755),
    "systemd/campus-network.service": ("usr/lib/systemd/system/campus-network.service", 0o644),
    "config/config.json": ("etc/campus-network/config.json", 0o644),
    "completion/campus-network": ("usr/share/bash-completion/completions/campus-network", 0o644),
    "README.md": ("usr/share/doc/campus-network/README.md", 0o644),
    "LICENSE": ("usr/share/doc/campus-network/copyright", 0o644),
}


def copy_file(source, target, mode=0o644):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((ROOT / source).read_bytes().replace(b"\r\n", b"\n"))
    target.chmod(mode)


def populate(stage):
    for source, (target, mode) in PAYLOAD.items():
        copy_file(source, stage / target, mode)


def build_deb(output, work):
    stage = work / "deb"
    populate(stage)
    control = stage / "DEBIAN"
    control.mkdir()
    for name in ("control", "conffiles", "postinst", "prerm", "postrm"):
        copy_file("debian/" + name, control / name, 0o755 if name in ("postinst", "prerm", "postrm") else 0o644)
    text = (control / "control").read_text()
    (control / "control").write_text(re.sub(r"(?m)^Version: .*", "Version: " + VERSION, text))
    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(output / ("campus-network_" + VERSION + "_all.deb"))], check=True)


def build_tar(output):
    target = output / ("campus-network_" + VERSION + "_linux-any.tar.gz")
    sources = list(PAYLOAD) + ["install.sh", "VERSION"]
    with target.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for source in sorted(sources):
                data = (ROOT / source).read_bytes().replace(b"\r\n", b"\n")
                entry = tarfile.TarInfo("campus-network-" + VERSION + "/" + source)
                entry.size = len(data)
                entry.mode = 0o755 if source in ("src/campus-network", "install.sh") else 0o644
                entry.mtime = 0
                archive.addfile(entry, io.BytesIO(data))


def build_rpm(output, work):
    top = work / "rpm"
    for directory in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
        (top / directory).mkdir(parents=True)
    stage = top / "payload"
    populate(stage)
    spec = top / "SPECS" / "campus-network.spec"
    spec.write_text("""Name: campus-network
Version: {version}
Release: 1
Summary: Persistent Ruijie ePortal campus network connection manager
License: MIT
URL: https://github.com/fsfgrafb/campus-network
BuildArch: noarch
Requires: python3 >= 3.9
Requires: /usr/bin/curl
Requires: systemd
Requires: ca-certificates
Requires: iproute
AutoReqProv: no

%description
Lightweight systemd service with persistent on/off mode, automatic recovery
and bounded exponential backoff. All local users can control its CLI.

%install
mkdir -p %{{buildroot}}
cp -a {stage}/. %{{buildroot}}/

%post
install -d -m 0755 /etc/campus-network
install -d -m 0700 /var/lib/campus-network
for file in /etc/campus-network/account /etc/campus-network/account.json; do
    if [ -f "$file" ]; then chown root:root "$file"; chmod 0600 "$file"; fi
done
systemctl enable campus-network.service >/dev/null 2>&1 || :
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload
    systemctl restart campus-network.service
fi

%preun
if [ "$1" -eq 0 ]; then
    systemctl disable --now campus-network.service >/dev/null 2>&1 || :
fi

%postun
if [ -d /run/systemd/system ]; then
    systemctl daemon-reload
    if [ "$1" -ge 1 ]; then systemctl try-restart campus-network.service || :; fi
fi

%files
%config(noreplace) /etc/campus-network/config.json
/usr/bin/campus-network
/usr/lib/systemd/system/campus-network.service
/usr/share/bash-completion/completions/campus-network
%doc /usr/share/doc/campus-network/README.md
%license /usr/share/doc/campus-network/copyright
""".format(version=VERSION, stage=stage), encoding="utf-8")
    subprocess.run(["rpmbuild", "--define", "_topdir " + str(top), "--define", "_build_id_links none", "-bb", str(spec)], check=True)
    for package in (top / "RPMS").rglob("*.rpm"):
        shutil.copy2(package, output / package.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("all", "deb", "rpm", "tar"), default="all")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", VERSION):
        parser.error("VERSION must contain a stable x.y.z version")
    source = (ROOT / "src/campus-network").read_text(encoding="utf-8")
    if not re.search(r"(?m)^VERSION\s*=\s*['\"]" + re.escape(VERSION) + r"['\"]", source):
        parser.error("VERSION and src/campus-network VERSION do not match")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="campus-network-build-") as temporary:
        work = Path(temporary)
        for name, builder in (("tar", lambda: build_tar(output)), ("deb", lambda: build_deb(output, work)), ("rpm", lambda: build_rpm(output, work))):
            if args.format in ("all", name):
                builder()
    packages = sorted(path for path in output.iterdir() if path.name.endswith((".deb", ".rpm", ".tar.gz")))
    (output / "SHA256SUMS").write_text("".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in packages))
    for package in packages:
        print(package.name + " (" + str(package.stat().st_size) + " bytes)")


if __name__ == "__main__":
    main()
