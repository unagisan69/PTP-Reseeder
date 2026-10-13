import tempfile
import unittest

from pathlib import Path

from ptp_reseeder.client import APIFile, Candidate, _parse_file_list
from ptp_reseeder.scanner import _api_files_match, looks_like_tv


class APIFileListTests(unittest.TestCase):
    def test_mapping_shape(self):
        files = _parse_file_list({"FileList": {"Movie.mkv": "1,234"}})
        self.assertEqual(files, (APIFile("Movie.mkv", 1234),))

    def test_record_shape(self):
        files = _parse_file_list({"Files": [{"Path": "Extras/a.srt", "Size": "42"}]})
        self.assertEqual(files, (APIFile("Extras/a.srt", 42),))

    def test_unknown_shape_is_not_usable(self):
        self.assertEqual(_parse_file_list({"FileList": ["Movie.mkv"]}), ())

    def test_api_file_list_selects_without_torrent_metadata(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "Release.Name"
            root.mkdir()
            (root / "movie.mkv").write_bytes(b"data")
            candidate = Candidate(1, "Release.Name", "Movie", "2000", (APIFile("movie.mkv", 4),))
            self.assertTrue(_api_files_match(root, candidate))

    def test_tv_patterns(self):
        self.assertTrue(looks_like_tv("Show.S02E03.1080p.mkv"))
        self.assertTrue(looks_like_tv("Show 2x03.mkv"))
        self.assertFalse(looks_like_tv("Apollo.13.1995.mkv"))


if __name__ == "__main__":
    unittest.main()
