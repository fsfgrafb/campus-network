"""Check that the release really offers one installer with all target choices."""

import importlib.util
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import universal


class UniversalPackageTests(unittest.TestCase):
    def test_single_archive_includes_all_targets_and_integrity_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "inputs", root / "release"
            source.mkdir()
            for name in ("campus-network_%s_all.deb", "campus-network-%s-1.noarch.rpm"):
                (source / (name % universal.VERSION)).write_bytes(b"native package fixture")
            for version in ("12", "13"):
                for arch in ("amd64", "arm64"):
                    (source / ("campus-network_%s_debian%s_%s_offline.tar.gz" % (universal.VERSION, version, arch))).write_bytes(b"repository fixture")
            universal.assemble(source, output)
            self.assertEqual(len(list(output.glob("*.tar.gz"))), 1)
            with tarfile.open(next(output.glob("*.tar.gz"))) as archive:
                prefix = "campus-network-" + universal.VERSION + "/"
                names = {member.name.removeprefix(prefix) for member in archive.getmembers()}
                self.assertTrue({"install.sh", "SHA256SUMS", "src/campus-network"} <= names)
                self.assertEqual(len([name for name in names if name.startswith("dependencies/")]), 4)
                self.assertFalse(any("python" in name for name in names))
                self.assertEqual(archive.getmember(prefix + "install.sh").mode, 0o755)

    def test_incomplete_architecture_set_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                universal.assemble(Path(temporary), Path(temporary) / "release")


if __name__ == "__main__":
    unittest.main()
