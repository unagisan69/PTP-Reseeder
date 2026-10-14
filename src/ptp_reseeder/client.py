from __future__ import annotations

import hashlib
import json
import os
import re
import time
import fcntl

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

from .config import Settings


class PTPError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candidate:
    torrent_id: int
    release_name: str
    movie_title: str
    year: str
    files: tuple["APIFile", ...]


@dataclass(frozen=True)
class APIFile:
    path: str
    size: int


def _parse_file_list(torrent: dict[str, Any]) -> tuple[APIFile, ...]:
    """Parse documented file-list data without fetching torrent metadata.

    PTP deployments have returned this field in more than one JSON shape, so
    accept mappings and arrays of path/size records. Unknown or incomplete
    shapes intentionally produce no files and therefore cannot be selected.
    """
    value: Any = None
    for key in ("FileList", "Filelist", "fileList", "filelist", "Files", "files"):
        if key in torrent:
            value = torrent[key]
            break
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return ()
    records: list[APIFile] = []
    if isinstance(value, dict):
        iterable = value.items()
        for path, size in iterable:
            try:
                records.append(APIFile(str(path), int(str(size).replace(",", ""))))
            except (TypeError, ValueError):
                return ()
    elif isinstance(value, list):
        for entry in value:
            if not isinstance(entry, dict):
                return ()
            path = next(
                (entry[k] for k in ("Path", "path", "Name", "name", "Filename", "filename") if k in entry),
                None,
            )
            size = next(
                (entry[k] for k in ("Size", "size", "Length", "length") if k in entry),
                None,
            )
            try:
                records.append(APIFile(str(path), int(str(size).replace(",", ""))))
            except (TypeError, ValueError):
                return ()
    return tuple(records)


class PTPClient:
    def __init__(
        self,
        settings: Settings,
        cache_dir: Path | None = None,
        notice: Callable[[str], None] | None = None,
    ):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update(
            {
                "ApiUser": settings.api_user,
                "ApiKey": settings.api_key,
                "User-Agent": "PTP-Reseeder/0.2 (personal exact-match reseed tool)",
            }
        )
        self.notice = notice or (lambda _message: None)
        default_cache = Path(
            os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
        ) / "ptp-reseeder"
        self.cache_dir = (cache_dir or default_cache).expanduser()
        self._rate_file = self.cache_dir / "request-history.json"

    def _cache_path(self, category: str, key: str, suffix: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8", "surrogateescape")).hexdigest()
        return self.cache_dir / category / f"{digest}{suffix}"

    @staticmethod
    def _fresh(path: Path, maximum_age: float) -> bool:
        try:
            return time.time() - path.stat().st_mtime <= maximum_age
        except OSError:
            return False

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.parent.chmod(0o700)
        except OSError:
            pass
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(path)

    def _get(
        self, endpoint: str, *, request_kind: str = "api", **kwargs: Any
    ) -> requests.Response:
        self._reserve_request(request_kind)
        try:
            response = self.session.get(
                self.settings.base_url.rstrip("/") + "/" + endpoint.lstrip("/"),
                timeout=(10, 60),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise PTPError(f"PTP request failed: {exc}") from exc
        if response.status_code == 403:
            raise PTPError("PTP returned 403; halted immediately as required by site rules")
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            detail = f" Retry-After: {retry_after} seconds." if retry_after else ""
            try:
                delay = max(3600, int(retry_after or 0))
            except ValueError:
                delay = 3600
            self._set_backoff(delay)
            raise PTPError(
                "PTP returned 429; halted to avoid extending the dynamic block."
                + detail
                + " Wait before resuming; cached work will not be requested again."
            )
        if response.status_code == 400 or 500 <= response.status_code < 600:
            self._set_backoff(300)
            raise PTPError(
                f"PTP returned HTTP {response.status_code}; halted for back-off before resuming"
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise PTPError(f"PTP returned HTTP {response.status_code}; stopped") from exc
        return response

    def _set_backoff(self, seconds: int) -> None:
        try:
            state = json.loads(self._rate_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            state = {}
        state["blocked_until"] = time.time() + seconds
        self._atomic_write(self._rate_file, json.dumps(state).encode("utf-8"))

    def _reserve_request(self, request_kind: str) -> None:
        """Coordinate API and torrent-download budgets across local processes."""
        if request_kind not in {"api", "torrent"}:
            raise ValueError(f"unknown request kind: {request_kind}")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.cache_dir.chmod(0o700)
        except OSError:
            pass
        lock_path = self.cache_dir / "request-history.lock"
        with lock_path.open("a+b") as lock:
            try:
                lock_path.chmod(0o600)
            except OSError:
                pass
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            while True:
                now = time.time()
                try:
                    state = json.loads(self._rate_file.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    state = {}
                blocked_until = float(state.get("blocked_until", 0))
                if blocked_until > now:
                    remaining = int(blocked_until - now) + 1
                    raise PTPError(
                        f"PTP back-off is active for another {remaining} seconds"
                    )
                legacy = state.pop("requests", None)
                if legacy is not None:
                    state.setdefault("api_requests", legacy)
                    state.setdefault("torrent_downloads", legacy)
                history_key = (
                    "api_requests" if request_kind == "api" else "torrent_downloads"
                )
                raw_history = state.get(history_key, [])
                window = (
                    3600
                    if request_kind == "api"
                    else self.settings.torrent_download_window
                )
                delay = (
                    self.settings.request_delay
                    if request_kind == "api"
                    else self.settings.torrent_download_delay
                )
                budget = (
                    self.settings.hourly_budget
                    if request_kind == "api"
                    else self.settings.torrent_download_budget
                )
                history = [
                    float(stamp)
                    for stamp in raw_history
                    if now - float(stamp) < window
                ]
                waits = [0.0]
                if history:
                    waits.append(delay - (now - history[-1]))
                if len(history) >= budget:
                    waits.append(window - (now - history[-budget]))
                wait = max(waits)
                if wait <= 0:
                    history.append(now)
                    state[history_key] = history
                    self._atomic_write(
                        self._rate_file,
                        json.dumps(state).encode("utf-8"),
                    )
                    return
                label = "API" if request_kind == "api" else ".torrent download"
                self.notice(f"PTP-safe {label} pacing: waiting {int(wait) + 1}s")
                time.sleep(wait)

    def search_filename(self, filename: str) -> list[Candidate]:
        cache = self._cache_path("searches", filename, ".json")
        try:
            if self._fresh(cache, 7 * 24 * 60 * 60):
                movies = json.loads(cache.read_text(encoding="utf-8")).get("Movies", [])
            else:
                response = self._get(
                    "torrents.php",
                    params={
                        "action": "advanced",
                        "filelist": filename,
                        "json": "noredirect",
                    },
                )
                data = response.json()
                movies = data.get("Movies", [])
                self._atomic_write(
                    cache,
                    json.dumps(data, ensure_ascii=False).encode("utf-8"),
                )
        except (ValueError, AttributeError, OSError, json.JSONDecodeError) as exc:
            raise PTPError("PTP returned an unexpected search response") from exc
        found: dict[int, Candidate] = {}
        for movie in movies:
            for torrent in movie.get("Torrents", []):
                torrent_id = int(torrent.get("Id") or torrent.get("TorrentId"))
                found[torrent_id] = Candidate(
                    torrent_id=torrent_id,
                    release_name=str(torrent.get("ReleaseName", torrent_id)),
                    movie_title=str(movie.get("Title", "Unknown")),
                    year=str(movie.get("Year", "")),
                    files=_parse_file_list(torrent),
                )
        return list(found.values())

    def download(self, torrent_id: int) -> tuple[bytes, str]:
        payload_cache = self.cache_dir / "torrents" / f"{torrent_id}.torrent"
        name_cache = self.cache_dir / "torrents" / f"{torrent_id}.name"
        if payload_cache.is_file() and name_cache.is_file():
            return payload_cache.read_bytes(), name_cache.read_text(encoding="utf-8")
        response = self._get(
            "torrents.php",
            request_kind="torrent",
            params={"action": "download", "id": torrent_id},
        )
        disposition = response.headers.get("Content-Disposition", "")
        match = re.search(r'filename="?([^";]+)', disposition, re.IGNORECASE)
        name = match.group(1) if match else f"ptp-{torrent_id}.torrent"
        name = Path(name).name
        if not name.lower().endswith(".torrent"):
            name += ".torrent"
        self._atomic_write(payload_cache, response.content)
        self._atomic_write(name_cache, name.encode("utf-8"))
        return response.content, name
