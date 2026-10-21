from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

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


def test_series_label_and_part_number_appear_in_title_and_description() -> None:
    title, description, _ = drive_short_metadata(
        job_id=7,
        source_video_id="v",
        confirmed_game="Fortnite",
        language="english",
        series="Fortnite Files",
        part=12,
    )

    assert "| Part 12 #Shorts" in title
    assert "📺 Fortnite Files — Part 12" in description


def test_no_part_number_is_published_by_default() -> None:
    title, description, _ = drive_short_metadata(
        job_id=42, source_video_id="v", confirmed_game=None
    )

    assert "الحلقة" not in title
    assert "الحلقة" not in description
    assert "📺" in description  # the series label is still shown


def test_empty_series_omits_series_markings() -> None:
    title, description, _ = drive_short_metadata(
        job_id=1, source_video_id="v", confirmed_game=None, series=""
    )

    assert "| الحلقة" not in title
    assert "| Part" not in title
    assert "📺" not in description


def test_negative_part_number_is_rejected() -> None:
    with pytest.raises(ValueError):
        drive_short_metadata(
            job_id=1, source_video_id="v", confirmed_game=None, part=-1
        )


def test_series_title_stays_within_100_chars_and_keeps_shorts() -> None:
    title, _, _ = drive_short_metadata(
        job_id=1,
        source_video_id="v",
        confirmed_game="Call of Duty Black Ops",
        series="Robinzo Archive Extended Cut",
        part=999,
    )

    assert len(title) <= 100
    assert title.endswith("#Shorts")
    assert "| الحلقة 999 #Shorts" in title


def test_explicit_arabic_part_number_appears_before_shorts() -> None:
    title, description, _ = drive_short_metadata(
        job_id=7, source_video_id="v", confirmed_game=None, part=7
    )

    assert "| الحلقة 7 #Shorts" in title
    assert "📺 أرشيف روبنزو — الحلقة 7" in description


def test_unknown_language_is_rejected() -> None:
    with pytest.raises(ValueError):
        drive_short_metadata(
            job_id=1, source_video_id="v", confirmed_game=None, language="fr"
        )


def test_metadata_generation_leaves_a_rendered_artifact_byte_identical(
    tmp_path: Path,
) -> None:
    """Golden guard: B1 is metadata-only and must not touch rendered bytes."""
    from robin_content_engine.production_runner import build_automatic_metadata

    artifact = tmp_path / "short.mp4"
    artifact.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"golden rendered bytes" * 8)
    before = hashlib.sha256(artifact.read_bytes()).hexdigest()

    drive_short_metadata(job_id=3, source_video_id="v", confirmed_game="Fortnite")
    build_automatic_metadata("Fortnite match", language="arabic")
    build_automatic_metadata("Fortnite match", language="english")

    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == before


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
