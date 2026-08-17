"""Small data models shared by the local transcription pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass
class Cue:
    """A timed subtitle cue.

    Times are expressed as seconds from the beginning of the media.  ``chinese``
    intentionally defaults to an empty string so an English transcript can be
    exported, translated by hand, and then read back without changing formats.
    """

    start: float
    end: float
    english: str
    chinese: str = ""

    def __post_init__(self) -> None:
        self.start = float(self.start)
        self.end = float(self.end)
        self.english = str(self.english)
        self.chinese = str(self.chinese)

        if not math.isfinite(self.start) or not math.isfinite(self.end):
            raise ValueError("cue timestamps must be finite numbers")
        if self.start < 0:
            raise ValueError("cue start must be non-negative")
        if self.end <= self.start:
            raise ValueError("cue end must be after cue start")
