#!/usr/bin/env python3
"""Combine native packages and four dependency repositories into one download."""

import argparse
import gzip
import hashlib
import io
from pathlib import Path
import tarfile

from build import PAYLOAD, ROOT, VERSION


def assemble(source, output):
    files = {name: ROOT / name for name in PAYLOAD}
    files.update({"VERSION": ROOT / "VERSION", "install.sh": ROOT / "tools/install-universal.sh",
                  "install-runtime.sh": ROOT / "install.sh"})
    for extension in ("deb", "rpm"):
        candidates = sorted(source.glob("*%s*.%s" % (VERSION, extension)))
        if len(candidates) != 1:
            raise ValueError("Expected exactly one native " + extension + " package")
        files["packages/" + candidates[0].name] = candidates[0]
    for version in ("12", "13"):
        for architecture in ("amd64", "arm64"):
            path = source / ("campus-network_%s_debian%s_%s_offline.tar.gz" % (VERSION, version, architecture))
            if not path.is_file():
                raise ValueError("Missing dependency repository: " + path.name)
            files["dependencies/debian%s-%s.tar.gz" % (version, architecture)] = path
    contents = {name: path.read_bytes() for name, path in files.items()}
    contents["SHA256SUMS"] = "".join(hashlib.sha256(data).hexdigest() + "  " + name + "\n"
                                         for name, data in sorted(contents.items())).encode()
    output.mkdir(parents=True, exist_ok=True)
    target = output / ("campus-network_%s_linux.tar.gz" % VERSION)
    with target.open("wb") as stream, gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for name, data in sorted(contents.items()):
                entry = tarfile.TarInfo("campus-network-" + VERSION + "/" + name)
                entry.size, entry.mtime = len(data), 0
                entry.mode = 0o755 if name in ("install.sh", "install-runtime.sh", "src/campus-network") else 0o644
                archive.addfile(entry, io.BytesIO(data))
    (output / "SHA256SUMS").write_text(hashlib.sha256(target.read_bytes()).hexdigest() + "  " + target.name + "\n")
    print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "dist")
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    args = parser.parse_args()
    assemble(args.input, args.output)
