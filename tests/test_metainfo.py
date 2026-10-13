import hashlib
import unittest

from pathlib import Path

from ptp_reseeder.metainfo import Metainfo, TorrentError


def enc(value):
    if isinstance(value, int):
        return b"i" + str(value).encode() + b"e"
    if isinstance(value, bytes):
        return str(len(value)).encode() + b":" + value
    if isinstance(value, list):
        return b"l" + b"".join(enc(v) for v in value) + b"e"
    if isinstance(value, dict):
        return b"d" + b"".join(enc(k) + enc(value[k]) for k in sorted(value)) + b"e"
    raise TypeError(value)


def multi_torrent(first=b"abcd", second=b"efgh", piece_length=3):
    content = first + second
    pieces = b"".join(
        hashlib.sha1(content[i : i + piece_length], usedforsecurity=False).digest()
        for i in range(0, len(content), piece_length)
    )
    return enc(
        {
            b"announce": b"https://tracker.invalid/announce",
            b"info": {
                b"name": b"Release",
                b"piece length": piece_length,
                b"pieces": pieces,
                b"files": [
                    {b"length": len(first), b"path": [b"a.mkv"]},
                    {b"length": len(second), b"path": [b"Extras", b"b.srt"]},
                ],
            },
        }
    )


class MetainfoTests(unittest.TestCase):
    def test_verifies_across_file_boundary(self):
        with __import__("tempfile").TemporaryDirectory() as raw:
            root = Path(raw) / "Release"
            (root / "Extras").mkdir(parents=True)
            (root / "a.mkv").write_bytes(b"abcd")
            (root / "Extras" / "b.srt").write_bytes(b"efgh")
            self.assertTrue(Metainfo.from_bytes(multi_torrent()).verify(root))

    def test_rejects_same_size_different_bytes(self):
        with __import__("tempfile").TemporaryDirectory() as raw:
            root = Path(raw) / "Release"
            (root / "Extras").mkdir(parents=True)
            (root / "a.mkv").write_bytes(b"abXd")
            (root / "Extras" / "b.srt").write_bytes(b"efgh")
            self.assertFalse(Metainfo.from_bytes(multi_torrent()).verify(root))

    def test_rejects_missing_file(self):
        with __import__("tempfile").TemporaryDirectory() as raw:
            root = Path(raw) / "Release"
            root.mkdir()
            (root / "a.mkv").write_bytes(b"abcd")
            self.assertFalse(Metainfo.from_bytes(multi_torrent()).verify(root))

    def test_rejects_renamed_single_file(self):
        with __import__("tempfile").TemporaryDirectory() as raw:
            content = b"movie"
            pieces = hashlib.sha1(content, usedforsecurity=False).digest()
            payload = enc({b"info": {b"name": b"release.mkv", b"length": 5, b"piece length": 16, b"pieces": pieces}})
            local = Path(raw) / "renamed.mkv"
            local.write_bytes(content)
            self.assertFalse(Metainfo.from_bytes(payload).verify(local))


if __name__ == "__main__":
    unittest.main()
