from pathlib import Path

import pytest
from pydantic import ValidationError

from robin_content_engine.models import GeneratedContent, VideoJob


def test_generated_content_normalizes_text_and_tags() -> None:
    content = GeneratedContent(
        title="  لقطة   مستحيلة في فورتنايت  ",
        description="  وصف مفيد   ومفصل للمشهد الأصلي داخل اللعبة.  ",
        tags=["#Fortnite", " fortnite ", "Gaming UAE", ""],
        script="  شوفوا كيف تغيرت المباراة   في آخر لحظة بطريقة ما كانت متوقعة.  ",
    )

    assert content.title == "لقطة مستحيلة في فورتنايت"
    assert content.tags == ["Fortnite", "Gaming UAE"]
    assert "  " not in content.script


def test_video_job_requires_a_source() -> None:
    with pytest.raises(ValidationError):
        VideoJob(
            id=1,
            source_title="Original gameplay",
            rights_confirmed=True,
        )


def test_local_source_requires_existing_file(tmp_path: Path) -> None:
    source = tmp_path / "owned.mp4"
    source.write_bytes(b"placeholder")
    job = VideoJob(
        id=2,
        source_path=str(source),
        source_title="Original gameplay",
        rights_confirmed=True,
    )

    assert job.local_source() == source


def test_remote_ingestion_is_disabled_in_mvp() -> None:
    job = VideoJob(
        id=3,
        source_url="https://example.com/video",
        source_title="Licensed footage",
        rights_confirmed=True,
    )

    with pytest.raises(ValueError, match="Remote source ingestion"):
        job.local_source()
