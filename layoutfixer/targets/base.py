"""What every text-access strategy provides to the engine."""

from __future__ import annotations

from dataclasses import dataclass


class TargetError(RuntimeError):
    """A user-facing reason why the text could not be read or replaced. Nothing was changed
    unless ``changed`` says so."""

    def __init__(self, message: str, changed: bool = False):
        super().__init__(message)
        self.changed = changed


class Unsupported(TargetError):
    pass


@dataclass
class FieldState:
    text: str                  # what the strategy can see: whole field, or only the selection
    sel_start: int             # Python indices into ``text``
    sel_end: int
    selection_only: bool = False  # ``text`` is just the selected text (whole field unknown)

    @property
    def has_selection(self) -> bool:
        return self.sel_end > self.sel_start


@dataclass(frozen=True)
class ReplaceResult:
    verified: bool             # we read the field back and it holds exactly the expected text
    note: str = ""


class TextTarget:
    kind = "base"

    def read(self) -> FieldState:
        raise NotImplementedError

    def replace(self, state: FieldState, start: int, end: int, new_text: str) -> ReplaceResult:
        """Make the field read ``new_text`` (the whole new contents of ``state.text``), where only
        ``new_text[start:end]`` differs from ``state.text[start:end]``."""
        raise NotImplementedError

    def close(self) -> None:
        """Always called by the engine, also after errors."""
