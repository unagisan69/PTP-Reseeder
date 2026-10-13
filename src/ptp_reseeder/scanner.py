from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .client import APIFile, Candidate, PTPClient
from .metainfo import Metainfo, TorrentError


MEDIA_SUFFIXES = {
    ".mkv", ".mp4", ".avi", ".m2ts", ".ts", ".mov", ".wmv", ".mpg", ".mpeg", ".iso"
}


@dataclass(frozen=True)
class Match:
    item: Path
    candidate: Candidate
    torrent_name: str
    payload: bytes | None
    total_size: int
    verified: bool


TV_PATTERNS = (
    __import__("re").compile(r"(?i)(?:^|[ ._-])S\d{1,2}E\d{1,3}(?:[ ._-]|$)"),
    __import__("re").compile(r"(?i)(?:^|[ ._-])\d{1,2}x\d{1,3}(?:[ ._-]|$)"),
    __import__("re").compile(r"(?i)(?:^|[ ._-])(?:complete[ ._-]+series|season[ ._-]+\d+)(?:[ ._-]|$)"),
)


def looks_like_tv(name: str) -> bool:
    return any(pattern.search(name) for pattern in TV_PATTERNS)


def library_items(root: Path) -> list[Path]:
    if not root.is_dir():
        raise ValueError(f"library is not a directory: {root}")
    return sorted(
        (p for p in root.iterdir() if not p.name.startswith(".")),
        key=lambda p: p.name.casefold(),
    )


def anchor_for(item: Path) -> Path | None:
    if item.is_file():
        return item
    if not item.is_dir():
        return None
    media = [p for p in item.rglob("*") if p.is_file() and p.suffix.lower() in MEDIA_SUFFIXES]
    if not media:
        media = [p for p in item.rglob("*") if p.is_file()]
    return max(media, key=lambda p: p.stat().st_size, default=None)


def find_match(
    client: PTPClient,
    item: Path,
    on_verify: Callable[[Candidate, int, int], None] | None = None,
    download: bool = True,
) -> tuple[Match | None, int]:
    anchor = anchor_for(item)
    if anchor is None:
        return None, 0
    if looks_like_tv(anchor.name):
        return None, -1
    candidates = client.search_filename(anchor.name)
    selected = next((candidate for candidate in candidates if _api_files_match(item, candidate)), None)
    if selected is None:
        return None, len(candidates)
    total_size = sum(file.size for file in selected.files)
    if not download:
        return Match(item, selected, "", None, total_size, False), len(candidates)

    # The decision has already been made from the documented search response.
    # Download exactly this selected torrent, then use hashes only as a safety check.
    payload, torrent_name = client.download(selected.torrent_id)
    try:
        meta = Metainfo.from_bytes(payload)
    except TorrentError:
        return None, len(candidates)
    callback = None
    if on_verify:
        callback = lambda done, total: on_verify(selected, done, total)
    if not meta.verify(item, callback):
        return None, len(candidates)
    return Match(item, selected, torrent_name, payload, meta.total_size, True), len(candidates)


def _api_files_match(item: Path, candidate: Candidate) -> bool:
    if not candidate.files:
        return False
    item = item.resolve()
    if item.is_file():
        if len(candidate.files) != 1:
            return False
        listed = candidate.files[0]
        return Path(listed.path.replace("\\", "/")).name == item.name and listed.size == item.stat().st_size
    if not item.is_dir() or item.name != candidate.release_name:
        return False
    for listed in candidate.files:
        parts = tuple(part for part in listed.path.replace("\\", "/").split("/") if part)
        if parts and parts[0] == candidate.release_name:
            parts = parts[1:]
        if not parts or any(part in {".", ".."} for part in parts):
            return False
        local = item.joinpath(*parts)
        try:
            local.resolve().relative_to(item)
            if not local.is_file() or local.stat().st_size != listed.size:
                return False
        except (OSError, ValueError):
            return False
    return True


def save_match(match: Match, destination: Path) -> Path:
    if match.payload is None or not match.verified:
        raise ValueError("cannot save an unverified preliminary match")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / match.torrent_name
    if target.exists():
        if target.read_bytes() == match.payload:
            return target
        target = destination / f"{target.stem}-{match.candidate.torrent_id}.torrent"
    target.write_bytes(match.payload)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target
