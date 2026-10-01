from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from robin_content_engine.publishing import PublishingError, build_publish_metadata  # noqa: E402
from robin_content_engine.shorts_metadata import drive_short_metadata  # noqa: E402


def test_confirmed_game_is_named_and_full_video_is_linked() -> None:
    title, description, tags = drive_short_metadata(
        job_id=0, source_video_id="MrZkqujTwdg", confirmed_game="Fortnite"
    )

    assert "Fortnite" in title and title.endswith("#Shorts")
    assert "https://www.youtube.com/watch?v=MrZkqujTwdg" in description
    assert "#Fortnite" in description
    assert tags[0] == "Fortnite"


def test_no_confirmed_game_never_names_a_game() -> None:
    for job_id in range(10):
        title, description, tags = drive_short_metadata(
            job_id=job_id, source_video_id="3xyU0yJwNMw", confirmed_game=None
        )
        for game in ("Fortnite", "Apex", "Roblox", "Call of Duty"):
            assert game not in title and game not in description and game not in tags
        assert "روبنزو" in title or "القناة" in title or "جلسة" in title


def test_consecutive_jobs_get_different_titles() -> None:
    titles = {
        drive_short_metadata(job_id=j, source_video_id="v", confirmed_game="Apex Legends")[0]
        for j in range(168, 174)
    }
    assert len(titles) == 6


def test_english_language_uses_english_templates() -> None:
    title, description, _ = drive_short_metadata(
        job_id=1, source_video_id="v", confirmed_game=None, language="english"
    )
    assert "#Shorts" in title and not any("\u0600" <= ch <= "\u06ff" for ch in title)
    assert "Full video" in description


def test_every_template_passes_publishing_validation() -> None:
    for language in ("arabic", "english"):
        for game in (None, "Call of Duty Black Ops"):
            for job_id in range(12):
                title, description, tags = drive_short_metadata(
                    job_id=job_id,
                    source_video_id="XqJcCA2aefg",
                    confirmed_game=game,
                    language=language,
                )
                try:
                    build_publish_metadata(title, description, tags)
                except PublishingError as exc:  # pragma: no cover - failure detail
                    raise AssertionError(f"{language}/{game}/{job_id}: {exc}") from exc
