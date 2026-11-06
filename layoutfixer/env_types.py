"""Small types shared by the Windows and macOS environments (no OS imports)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SwitchResult:
    ok: bool
    message: str
    before: str | None = None
    after: str | None = None
