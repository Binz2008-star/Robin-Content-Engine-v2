from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

from robin_content_engine import segment_ledger as sl  # noqa: E402
from robin_content_engine.clip_selector import HighlightCandidate  # noqa: E402
from robin_content_engine.segment_ledger import (  # noqa: E402
    SegmentLedgerError,
    UsedSegment,
    fetch_used_segments,
    first_unused_rank,
    is_unused,
    ledger_url,
    parse_ledger_url,
)

VID = "MrZkqujTwdg"


def _cand(start: float, end: float, score: float = 1.0) -> HighlightCandidate:
    return HighlightCandidate(
        start_seconds=start,
        end_seconds=end,
        score=score,
        audio_score=0.0,
        motion_score=0.0,
        scene_signal=0.0,
        reason="test",
    )


# ---------------------------------------------------------------------------
# URL format
# ---------------------------------------------------------------------------


def test_ledger_url_round_trips() -> None:
    url = ledger_url(VID, 120.0, 155.25)

    assert url == f"https://www.youtube.com/watch?v={VID}#segment=120.000-155.250"
    assert parse_ledger_url(url) == UsedSegment(VID, 120.0, 155.25)


@pytest.mark.parametrize(
    ("vid", "start", "end"),
    [("short", 0, 10), (VID, 10, 10), (VID, 20, 10), (VID, -1, 10)],
)
def test_ledger_url_rejects_bad_input(vid: str, start: float, end: float) -> None:
    with pytest.raises(SegmentLedgerError):
        ledger_url(vid, start, end)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        f"https://www.youtube.com/watch?v={VID}",  # plain URL, no segment
        f"https://www.youtube.com/watch?v={VID}#segment=50-40",  # inverted
        f"https://evil.example/watch?v={VID}#segment=1-2",  # wrong host
        "/local/capture.mp4",
    ],
)
def test_parse_ignores_non_ledger_values(value: str | None) -> None:
    assert parse_ledger_url(value) is None


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_first_unused_rank_skips_used_segments() -> None:
    candidates = [_cand(100, 130), _cand(300, 330), _cand(500, 530)]
    used = [UsedSegment(VID, 95, 125), UsedSegment(VID, 320, 350)]

    assert first_unused_rank(candidates, used) == 3


def test_first_unused_rank_is_one_with_empty_ledger() -> None:
    assert first_unused_rank([_cand(0, 30), _cand(60, 90)], []) == 1


def test_first_unused_rank_none_when_exhausted() -> None:
    candidates = [_cand(0, 30), _cand(60, 90)]
    used = [UsedSegment(VID, 0, 100)]

    assert first_unused_rank(candidates, used) is None


def test_touching_or_tiny_overlap_is_allowed() -> None:
    used = [UsedSegment(VID, 100, 130)]

    assert is_unused(_cand(130, 160), used)  # touching
    assert is_unused(_cand(129.6, 160), used)  # 0.4s rounding overlap
    assert not is_unused(_cand(129.0, 160), used)  # 1s shared footage
    assert not is_unused(_cand(110, 120), used)  # fully inside


# ---------------------------------------------------------------------------
# Read-only DB fetch
# ---------------------------------------------------------------------------


class FakeConn:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, Any]] = []

    def __enter__(self) -> FakeConn:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> FakeConn:
        self.executed.append((sql, params))
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


def test_fetch_used_segments_parses_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConn(
        [
            (ledger_url(VID, 300, 330),),
            (ledger_url(VID, 10, 40),),
            ("garbage",),
        ]
    )
    monkeypatch.setattr(sl.psycopg, "connect", lambda url: conn)

    segments = fetch_used_segments(SimpleNamespace(database_url="x"), VID)  # type: ignore[arg-type]

    assert segments == [UsedSegment(VID, 10, 40), UsedSegment(VID, 300, 330)]
    sql, params = conn.executed[0]
    assert sql.strip().upper().startswith("SELECT")
    assert params == (f"https://www.youtube.com/watch?v={VID}#segment=%",)


def test_fetch_used_segments_rejects_bad_video_id() -> None:
    with pytest.raises(SegmentLedgerError):
        fetch_used_segments(SimpleNamespace(database_url="x"), "x%' OR 1=1")  # type: ignore[arg-type]


def test_fetch_usage_counts_counts_segments_per_video(monkeypatch: pytest.MonkeyPatch) -> None:
    other = "3xyU0yJwNMw"
    conn = FakeConn(
        [
            (ledger_url(VID, 10, 40),),
            (ledger_url(other, 1, 20),),
            (ledger_url(other, 50, 70),),
            ("garbage",),
        ]
    )
    monkeypatch.setattr(sl.psycopg, "connect", lambda url: conn)

    counts = sl.fetch_usage_counts(SimpleNamespace(database_url="x"))  # type: ignore[arg-type]

    assert counts == {VID: 1, other: 2}
    sql, _params = conn.executed[0]
    assert sql.strip().upper().startswith("SELECT")
