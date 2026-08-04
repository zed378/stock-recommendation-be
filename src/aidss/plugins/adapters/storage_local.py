"""Filesystem-backed StorageProvider for development and self-hosted setups.

The production counterpart is an object-storage adapter behind the same
contract, so switching is a change to ``AIDSS_STORAGE_PROVIDER`` alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from aidss.config import Settings
from aidss.plugins.interfaces import StorageProvider
from aidss.plugins.registry import register


@register
class LocalStorageProvider(StorageProvider):
    name: ClassVar[str] = "local"

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_settings(cls, settings: Settings) -> LocalStorageProvider:
        return cls(settings.local_storage_root)

    def _path(self, key: str) -> Path:
        # Reject path traversal: the resolved key must stay inside the root.
        candidate = (self._root / key).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise ValueError(f"Key {key!r} escapes the storage root")
        return candidate

    def store(
        self, key: str, data: bytes, *, content_type: str = "application/octet-stream"
    ) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"file://{path}"

    def retrieve(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise KeyError(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()
