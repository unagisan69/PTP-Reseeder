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

    @classmethod
    def from_environment(cls) -> "Settings":
        user = os.environ.get("PTP_API_USER", "").strip()
        key = os.environ.get("PTP_API_KEY", "").strip()
        if not user or not key:
            raise ValueError("set PTP_API_USER and PTP_API_KEY in your environment")
        return cls(user, key)
