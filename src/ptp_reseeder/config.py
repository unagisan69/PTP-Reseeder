from __future__ import annotations

import os

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_user: str
    api_key: str
    base_url: str = "https://passthepopcorn.me/"
    # 30 seconds is 120 requests/hour: a 20% safety margin under PTP's stated
    # 150/hour hard ceiling, while also satisfying the 1 request/2 seconds rule.
    request_delay: float = 30.0
    hourly_budget: int = 120
    # Staff separately permits at most 300 .torrent downloads per four-hour
    # window. Keep a margin and avoid bursts even though this is not API use.
    torrent_download_delay: float = 52.0
    torrent_download_budget: int = 280
    torrent_download_window: int = 4 * 60 * 60

    @classmethod
    def from_environment(cls) -> "Settings":
        user = os.environ.get("PTP_API_USER", "").strip()
        key = os.environ.get("PTP_API_KEY", "").strip()
        if not user or not key:
            raise ValueError("set PTP_API_USER and PTP_API_KEY in your environment")
        return cls(user, key)
