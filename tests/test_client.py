import json
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from ptp_reseeder.client import PTPClient
from ptp_reseeder.config import Settings


class RequestBudgetTests(unittest.TestCase):
    def test_api_and_torrent_downloads_use_separate_histories(self):
        with tempfile.TemporaryDirectory() as raw:
            client = PTPClient(Settings("user", "key"), cache_dir=Path(raw))
            with patch("ptp_reseeder.client.time.time", return_value=10_000):
                client._reserve_request("api")
                client._reserve_request("torrent")

            state = json.loads(
                (Path(raw) / "request-history.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["api_requests"], [10_000])
            self.assertEqual(state["torrent_downloads"], [10_000])

    def test_legacy_history_is_conservatively_migrated_to_both_budgets(self):
        with tempfile.TemporaryDirectory() as raw:
            cache = Path(raw)
            (cache / "request-history.json").write_text(
                json.dumps({"requests": [1_000]}), encoding="utf-8"
            )
            client = PTPClient(Settings("user", "key"), cache_dir=cache)
            with patch("ptp_reseeder.client.time.time", return_value=10_000):
                client._reserve_request("api")

            state = json.loads(
                (cache / "request-history.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("requests", state)
            self.assertEqual(state["api_requests"], [10_000])
            self.assertEqual(state["torrent_downloads"], [1_000])


if __name__ == "__main__":
    unittest.main()
