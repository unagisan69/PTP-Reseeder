"""Small, strict bencode codec used to inspect torrent metadata."""

from __future__ import annotations

from typing import Any


class BencodeError(ValueError):
    pass


def decode(data: bytes) -> Any:
    def parse(pos: int) -> tuple[Any, int]:
        if pos >= len(data):
            raise BencodeError("unexpected end of data")
        token = data[pos : pos + 1]
        if token == b"i":
            end = data.find(b"e", pos + 1)
            if end < 0:
                raise BencodeError("unterminated integer")
            raw = data[pos + 1 : end]
            if not raw or (raw.startswith(b"-") and len(raw) == 1):
                raise BencodeError("invalid integer")
            try:
                return int(raw), end + 1
            except ValueError as exc:
                raise BencodeError("invalid integer") from exc
        if token == b"l":
            result: list[Any] = []
            pos += 1
            while pos < len(data) and data[pos : pos + 1] != b"e":
                value, pos = parse(pos)
                result.append(value)
            if pos >= len(data):
                raise BencodeError("unterminated list")
            return result, pos + 1
        if token == b"d":
            result: dict[bytes, Any] = {}
            pos += 1
            while pos < len(data) and data[pos : pos + 1] != b"e":
                key, pos = parse(pos)
                if not isinstance(key, bytes):
                    raise BencodeError("dictionary key is not bytes")
                result[key], pos = parse(pos)
            if pos >= len(data):
                raise BencodeError("unterminated dictionary")
            return result, pos + 1
        if b"0" <= token <= b"9":
            colon = data.find(b":", pos)
            if colon < 0:
                raise BencodeError("invalid byte string")
            try:
                length = int(data[pos:colon])
            except ValueError as exc:
                raise BencodeError("invalid byte string length") from exc
            start, end = colon + 1, colon + 1 + length
            if end > len(data):
                raise BencodeError("truncated byte string")
            return data[start:end], end
        raise BencodeError(f"unexpected token at offset {pos}")

    value, final = parse(0)
    if final != len(data):
        raise BencodeError("trailing data")
    return value
