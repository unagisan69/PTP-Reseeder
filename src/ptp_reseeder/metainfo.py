from __future__ import annotations

import hashlib
import os

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable

from .bencode import BencodeError, decode


class TorrentError(ValueError):
    pass


@dataclass(frozen=True)
class TorrentFile:
    parts: tuple[str, ...]
    length: int


@dataclass(frozen=True)
class Metainfo:
    name: str
    files: tuple[TorrentFile, ...]
    piece_length: int
    pieces: tuple[bytes, ...]

    @classmethod
    def from_bytes(cls, payload: bytes) -> "Metainfo":
        try:
            root = decode(payload)
            info = root[b"info"]
            name = _text(info[b"name"])
            piece_length = int(info[b"piece length"])
            raw_pieces = info[b"pieces"]
        except (BencodeError, KeyError, TypeError, ValueError) as exc:
            raise TorrentError("invalid v1 torrent metadata") from exc
        if not isinstance(info, dict) or piece_length <= 0:
            raise TorrentError("invalid torrent info dictionary")
        if not isinstance(raw_pieces, bytes) or len(raw_pieces) % 20:
            raise TorrentError("invalid v1 piece hashes")
        pieces = tuple(raw_pieces[i : i + 20] for i in range(0, len(raw_pieces), 20))
        if b"files" in info:
            parsed = []
            for item in info[b"files"]:
                parts = tuple(_text(p) for p in item[b"path"])
                _safe_parts(parts)
                parsed.append(TorrentFile(parts, int(item[b"length"])))
            files = tuple(parsed)
        else:
            files = (TorrentFile((name,), int(info[b"length"])),)
        if not files or any(f.length < 0 for f in files):
            raise TorrentError("invalid torrent file list")
        expected = (sum(f.length for f in files) + piece_length - 1) // piece_length
        if expected != len(pieces):
            raise TorrentError("piece count does not match torrent size")
        return cls(name, files, piece_length, pieces)

    @property
    def multi_file(self) -> bool:
        return not (len(self.files) == 1 and self.files[0].parts == (self.name,))

    @property
    def total_size(self) -> int:
        return sum(f.length for f in self.files)

    def local_files(self, item: Path) -> tuple[Path, ...] | None:
        item = item.resolve()
        if self.multi_file:
            if not item.is_dir() or item.name != self.name:
                return None
            paths = tuple(item.joinpath(*f.parts) for f in self.files)
        else:
            if item.is_file() and item.name == self.name:
                paths = (item,)
            elif item.is_dir():
                paths = (item / self.name,)
            else:
                return None
        try:
            item_root = item if item.is_dir() else item.parent
            for path, tor_file in zip(paths, self.files):
                path.resolve().relative_to(item_root.resolve())
                if not path.is_file() or path.stat().st_size != tor_file.length:
                    return None
        except (OSError, ValueError):
            return None
        return paths

    def verify(self, item: Path, progress: Callable[[int, int], None] | None = None) -> bool:
        paths = self.local_files(item)
        if paths is None:
            return False
        stream = ConcatenatedReader(paths)
        try:
            for index, expected in enumerate(self.pieces, start=1):
                block = stream.read(self.piece_length)
                if hashlib.sha1(block, usedforsecurity=False).digest() != expected:
                    return False
                if progress:
                    progress(index, len(self.pieces))
            return stream.read(1) == b""
        finally:
            stream.close()


def _text(value: bytes) -> str:
    if not isinstance(value, bytes):
        raise TorrentError("torrent path is not bytes")
    return value.decode("utf-8", "surrogateescape")


def _safe_parts(parts: tuple[str, ...]) -> None:
    if not parts:
        raise TorrentError("empty torrent path")
    for part in parts:
        if part in {"", ".", ".."} or "/" in part or "\\" in part or os.path.isabs(part):
            raise TorrentError("unsafe torrent path")
        if PurePosixPath(part).name != part:
            raise TorrentError("unsafe torrent path")


class ConcatenatedReader:
    def __init__(self, paths: tuple[Path, ...]):
        self.paths = iter(paths)
        self.current: BinaryIO | None = None

    def read(self, amount: int) -> bytes:
        result = bytearray()
        while len(result) < amount:
            if self.current is None:
                try:
                    self.current = next(self.paths).open("rb")
                except StopIteration:
                    break
            chunk = self.current.read(amount - len(result))
            if chunk:
                result.extend(chunk)
            else:
                self.current.close()
                self.current = None
        return bytes(result)

    def close(self) -> None:
        if self.current is not None:
            self.current.close()
            self.current = None
