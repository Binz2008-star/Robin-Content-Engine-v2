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

from robin_content_engine.ai_logic import (  # noqa: E402
    MetadataValidationError,
    validate_generated_metadata,
)
from robin_content_engine.channel_metadata import (  # noqa: E402
    ChannelMetadataFixer,
    MetadataFixPlan,
    PlanEntry,
    detect_game,
    needs_metadata_fix,
)
from robin_content_engine.youtube_auth import ChannelIdentity  # noqa: E402

EXPECTED_CHANNEL_ID = "UC_expected"


class FakeAuth:
    def __init__(self, channel_id: str = EXPECTED_CHANNEL_ID) -> None:
        self.channel_id = channel_id
        self.loaded = 0

    def load_credentials(self) -> str:
        self.loaded += 1
        return "creds"

    def fetch_channel_identity(self, credentials: Any) -> ChannelIdentity:
        return ChannelIdentity(channel_id=self.channel_id, title="Test Channel")


class FakeGenerator:
    def generate(self, context: str, language: str = "arabic") -> Any:
        return SimpleNamespace(
            title="جلسة فورتنايت نارية مع روبن", description="وصف تجريبي مختصر.", tags=["فورتنايت"]
        )

    def generate_archive_metadata(
        self, old_title: str, published_at: str, language: str = "arabic"
    ) -> Any:
        return SimpleNamespace(
            title="مقطع قديم من الأرشيف",
            description="لقطة من أرشيف القناة.",
            tags=["أرشيف"],
        )


class FakeYouTube:
    def __init__(self) -> None:
        self.updated: list[dict[str, Any]] = []

    def videos(self) -> FakeVideos:
        return FakeVideos(self)


class FakeVideos:
    def __init__(self, parent: FakeYouTube) -> None:
        self.parent = parent

    def update(self, part: str, body: dict[str, Any]) -> FakeRequest:
        self.parent.updated.append(body)
        return FakeRequest()


class FakeRequest:
    def execute(self) -> dict[str, Any]:
        return {"kind": "youtube#video"}


class FakeCursor:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> FakeCursor:
        self.executed.append((sql, params))
        return self

    def fetchall(self) -> list[Any]:
        return list(self.rows)


class FakeConn:
    def __init__(self, rows: list[Any]) -> None:
        self.cursor = FakeCursor(rows)

    def __enter__(self) -> FakeConn:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> FakeCursor:
        return self.cursor.execute(sql, params)


def _fake_settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        database_url="postgresql://fake",
        youtube_expected_channel_id=EXPECTED_CHANNEL_ID,
        youtube_category_id="20",
        work_dir=tmp_path,
    )


# ---------------------------------------------------------------------------
# detect_game / needs_metadata_fix
# ---------------------------------------------------------------------------


def test_detect_game_from_titles() -> None:
    assert detect_game("Fortnite_20211205165131") == "Fortnite"
    assert detect_game("Apex Legends_20201208173122") == "Apex Legends"
    assert detect_game("Black ops") == "Call of Duty Black Ops"
    assert detect_game("Roblox gameplay") == "Roblox"
    assert detect_game("Ghfg#y") is None


@pytest.mark.parametrize(
    ("title", "description", "expected"),
    [
        ("Robin_CR8's Live PS4 Broadcast", "x", True),
        ("Fortnite_20211205165131", "x", True),
        ("Apex", "", True),
        ("Furniture", "", True),
        ("Ghfg#y", "", True),
        ("1 August 2021", "x", True),
        ("", "x", True),
        ("جلسة فورتنايت نارية مع روبن", "وصف عربي كامل.", False),
    ],
)
def test_needs_metadata_fix(title: str, description: str, expected: bool) -> None:
    assert needs_metadata_fix(title, description) is expected


# ---------------------------------------------------------------------------
# validate_generated_metadata
# ---------------------------------------------------------------------------


def test_validate_accepts_clean_metadata() -> None:
    validate_generated_metadata(
        "جلسة فورتنايت نارية مع روبن", "وصف تجريبي مختصر ومفيد.", ["فورتنايت", "قيمنق"]
    )


@pytest.mark.parametrize(
    "text",
    ["شاهد قبل الحذف", "بث مباشر", "بطولة كبرى", "حطمنا الرقم القياسي"],
)
def test_validate_rejects_banned_phrases(text: str) -> None:
    with pytest.raises(MetadataValidationError, match="banned"):
        validate_generated_metadata(text, "وصف تجريبي مختصر ومفيد.", [])


def test_validate_rejects_empty_title() -> None:
    with pytest.raises(MetadataValidationError, match="title"):
        validate_generated_metadata("", "وصف تجريبي.", [])


# ---------------------------------------------------------------------------
# MetadataFixPlan persistence
# ---------------------------------------------------------------------------


def test_plan_persistence_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    plan = MetadataFixPlan(path)
    plan.upsert(PlanEntry("vid1", "Old", "2021-01-01", "pending", game="Fortnite"))
    plan.upsert(PlanEntry("vid2", "Old2", "", "done", new_title="جديد", new_description="و"))
    reloaded = MetadataFixPlan(path)
    assert reloaded.existing("vid1") is not None
    assert reloaded.existing("vid1").game == "Fortnite"
    assert reloaded.existing("vid2").state == "done"
    assert len(reloaded.pending()) == 1


# ---------------------------------------------------------------------------
# discover (monkeypatched DB) + apply (monkeypatched YouTube client)
# ---------------------------------------------------------------------------


def test_discover_registers_pending_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import robin_content_engine.channel_metadata as cm

    rows = [
        ("vidA", "Fortnite_20211205165131", "", None),
        ("vidB", "جلسة فورتنايت نارية مع روبن", "وصف عربي كامل.", None),
        ("vidC", "Ghfg#y", "", None),
    ]
    monkeypatch.setattr(cm.psycopg, "connect", lambda url: FakeConn(rows))

    fixer = ChannelMetadataFixer(
        _fake_settings(tmp_path), FakeAuth(), FakeGenerator()  # type: ignore[arg-type]
    )
    discovered = fixer.discover()
    ids = {entry.video_id for entry in discovered}
    assert ids == {"vidA", "vidC"}
    assert fixer.plan.existing("vidB") is None


def test_apply_resumes_and_respects_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import robin_content_engine.channel_metadata as cm

    fixer = ChannelMetadataFixer(
        _fake_settings(tmp_path), FakeAuth(), FakeGenerator()  # type: ignore[arg-type]
    )
    for vid, title in [("v1", "Apex"), ("v2", "Fortnite_2021")]:
        entry = PlanEntry(vid, title, "2021-01-01", "pending", game=detect_game(title))
        fixer.generate_for(entry)

    fake_youtube = FakeYouTube()
    monkeypatch.setattr(cm, "build", lambda *a, **k: fake_youtube)

    applied, failed, _failures = fixer.apply(max_updates=1)
    assert applied == 1
    assert failed == 0
    assert len(fake_youtube.updated) == 1
    assert fixer.plan.existing("v1").state == "done"
    assert fixer.plan.existing("v2").state == "pending"

    # resume: the second entry is applied now
    applied2, _, _ = fixer.apply(max_updates=1)
    assert applied2 == 1
    assert fixer.plan.existing("v2").state == "done"
