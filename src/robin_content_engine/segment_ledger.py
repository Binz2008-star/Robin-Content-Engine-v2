"""Used-segment ledger - never cut the same moment of a source video twice.

When the PC-less runner makes a new Short from one of the channel's long
videos, the exact segment it used is recorded in the queue job's existing
`source_url` column as a normal watch URL plus a fragment:

    https://www.youtube.com/watch?v=<video_id>#segment=<start>-<end>

(seconds, 3 decimals). No schema change: the column already exists, the
URL still opens the source video, and the fragment is ignored by browsers.

Before cutting, the runner reads every recorded segment for that video and
picks the best-scoring highlight candidate that does not overlap any of
them. Every queue row counts - including failed/quarantined ones - so a
segment that was already tried is never silently re-tried as "new".
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import psycopg

from .clip_selector import HighlightCandidate
from .config import Settings

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_LEDGER_RE = re.compile(
    r"^https://www\.youtube\.com/watch\?v=(?P<vid>[A-Za-z0-9_-]{11})"
    r"#segment=(?P<start>\d+(?:\.\d+)?)-(?P<end>\d+(?:\.\d+)?)$"
)

# Candidates may touch a used segment, but may not share more than this
# much footage with it (container/keyframe rounding around cut points).
DEFAULT_MAX_OVERLAP_SECONDS = 0.5


class SegmentLedgerError(RuntimeError):
    pass


@dataclass(frozen=True)
class UsedSegment:
    video_id: str
    start_seconds: float
    end_seconds: float


def ledger_url(video_id: str, start_seconds: float, end_seconds: float) -> str:
    """The `source_url` value recording that [start, end) of `video_id`
    was used."""
    if not _VIDEO_ID_RE.match(video_id):
        raise SegmentLedgerError(f"Invalid YouTube video id: {video_id!r}")
    if not (0 <= start_seconds < end_seconds):
        raise SegmentLedgerError(
            f"Invalid segment {start_seconds!r}-{end_seconds!r}: need 0 <= start < end."
        )
    return (
        f"https://www.youtube.com/watch?v={video_id}"
        f"#segment={start_seconds:.3f}-{end_seconds:.3f}"
    )


def parse_ledger_url(value: str | None) -> UsedSegment | None:
    """The segment recorded in a `source_url`, or None when the value is not
    a ledger URL (plain URLs, local-capture jobs, NULL)."""
    if not value:
        return None
    match = _LEDGER_RE.match(value.strip())
    if not match:
        return None
    start = float(match["start"])
    end = float(match["end"])
    if end <= start:
        return None
    return UsedSegment(match["vid"], start, end)


def fetch_used_segments(settings: Settings, video_id: str) -> list[UsedSegment]:
    """Every segment of `video_id` already recorded in the queue, in any
    status. Read-only SELECT."""
    if not _VIDEO_ID_RE.match(video_id):
        raise SegmentLedgerError(f"Invalid YouTube video id: {video_id!r}")
    prefix = f"https://www.youtube.com/watch?v={video_id}#segment="
    with psycopg.connect(settings.database_url) as conn:
        rows = conn.execute(
            "SELECT source_url FROM video_queue WHERE source_url LIKE %s",
            (prefix + "%",),
        ).fetchall()
    segments = [parse_ledger_url(row[0]) for row in rows]
    return sorted(
        (s for s in segments if s is not None and s.video_id == video_id),
        key=lambda s: (s.start_seconds, s.end_seconds),
    )


def overlap_seconds(start: float, end: float, used: UsedSegment) -> float:
    return max(0.0, min(end, used.end_seconds) - max(start, used.start_seconds))


def is_unused(
    candidate: HighlightCandidate,
    used: Iterable[UsedSegment],
    *,
    max_overlap_seconds: float = DEFAULT_MAX_OVERLAP_SECONDS,
) -> bool:
    return all(
        overlap_seconds(candidate.start_seconds, candidate.end_seconds, segment)
        <= max_overlap_seconds
        for segment in used
    )


def first_unused_rank(
    candidates: Sequence[HighlightCandidate],
    used: Sequence[UsedSegment],
    *,
    max_overlap_seconds: float = DEFAULT_MAX_OVERLAP_SECONDS,
) -> int | None:
    """1-based rank (the production runner's `rank` argument) of the
    best-scoring candidate that does not overlap any used segment, or None
    when every candidate is used up. `candidates` must be in rank order, as
    returned by the highlight analysis."""
    for index, candidate in enumerate(candidates, start=1):
        if is_unused(candidate, used, max_overlap_seconds=max_overlap_seconds):
            return index
    return None
