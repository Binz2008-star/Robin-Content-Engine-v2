from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from .ai_logic import (
    ContentGenerationError,
    ContentGenerator,
    MetadataValidationError,
    build_ai_context,
    validate_generated_metadata,
)
from .config import Settings
from .youtube_auth import YouTubeAuth

# Rough YouTube Data API cost (quota units) of a videos().update call.
_VIDEO_UPDATE_COST = 1600

# Junk/default title patterns that identify a video as needing a proper
# title: auto-generated PS4/Xbox capture names, single-word titles,
# date-only titles, hash-garbage titles, etc.
_JUNK_TITLE_RE = re.compile(
    r"^\s*(?:"
    r".*\b(?:broadcast|live stream|livestream)\b.*|"  # "Robin_CR8's Live PS4 Broadcast"
    r"(?:fortnite|apex|black ops|call of duty)[_\s]*\d+.*|"  # "Fortnite_20211205165131"
    r"(?:apex|fortnite|furniture|gh|ggg|ghfg#?y|gg|gfg|gf|black ops)\s*$|"  # single junk word
    r"\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+\d{4}|"  # date-only title
    r"\d{4}-\d{2}-\d{2}|"
    r"linda|furniture|gh\b|ghg\b"
    r")",
    re.IGNORECASE,
)

_GAME_TITLE_RE = re.compile(
    r"(fortnite|apex|roblox|black ops|call of duty)", re.IGNORECASE
)


class ChannelMetadataError(RuntimeError):
    pass


def detect_game(title: str) -> str | None:
    """Best-effort game-name detection from a video title. Returns the game
    name when the title clearly names one, else None."""
    t = (title or "").lower()
    if "fortnite" in t:
        return "Fortnite"
    if "apex" in t:
        return "Apex Legends"
    if "roblox" in t:
        return "Roblox"
    if "black ops" in t or "call of duty" in t:
        return "Call of Duty Black Ops"
    return None


def needs_metadata_fix(title: str, description: str) -> bool:
    """A video needs a fix when its description is empty/whitespace or its
    title is one of the known junk/default patterns. Idempotency comes from
    this predicate: once fixed, the title is Arabic and the description is
    non-empty, so a re-run skips it."""
    if not description or not description.strip():
        return True
    if not title or not title.strip():
        return True
    return _JUNK_TITLE_RE.fullmatch(title.strip()) is not None


@dataclass
class PlanEntry:
    video_id: str
    old_title: str
    published_at: str
    state: str  # pending | done | skipped | failed
    game: str | None = None
    new_title: str | None = None
    new_description: str | None = None
    new_tags: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "old_title": self.old_title,
            "published_at": self.published_at,
            "state": self.state,
            "game": self.game,
            "new_title": self.new_title,
            "new_description": self.new_description,
            "new_tags": self.new_tags,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanEntry:
        return cls(
            video_id=str(data["video_id"]),
            old_title=str(data.get("old_title", "")),
            published_at=str(data.get("published_at", "")),
            state=str(data.get("state", "pending")),
            game=data.get("game"),
            new_title=data.get("new_title"),
            new_description=data.get("new_description"),
            new_tags=list(data.get("new_tags") or []),
            detail=str(data.get("detail", "")),
        )


class MetadataFixPlan:
    """Durable, resumable plan of per-video metadata fixes persisted as
    work/metadata_plan.json. State transitions are atomic (tmp + replace)
    so an interrupted or quota-limited run resumes exactly where it left
    off instead of re-burning DeepSeek calls and YouTube quota."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.entries: list[PlanEntry] = []
        if path.is_file():
            self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, list):
            return
        self.entries = [
            PlanEntry.from_dict(item)
            for item in raw
            if isinstance(item, dict) and item.get("video_id")
        ]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        tmp_path.write_text(
            json.dumps([entry.to_dict() for entry in self.entries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

    def existing(self, video_id: str) -> PlanEntry | None:
        for entry in self.entries:
            if entry.video_id == video_id:
                return entry
        return None

    def upsert(self, entry: PlanEntry) -> None:
        existing = self.existing(entry.video_id)
        if existing is not None:
            self.entries[self.entries.index(existing)] = entry
        else:
            self.entries.append(entry)
        self.save()

    def pending(self) -> list[PlanEntry]:
        return [entry for entry in self.entries if entry.state == "pending"]

    def done_count(self) -> int:
        return sum(1 for entry in self.entries if entry.state == "done")


class ChannelMetadataFixer:
    """Fix titles/descriptions/tags across the channel's videos. Reads the
    stored channel snapshot (youtube_videos), builds a resumable plan,
    generates validated Arabic metadata, and applies it with a hard budget
    on the number of YouTube updates per invocation (quota-aware)."""

    def __init__(
        self,
        settings: Settings,
        auth: YouTubeAuth,
        generator: ContentGenerator,
        plan_path: Path | None = None,
    ) -> None:
        self.settings = settings
        self.auth = auth
        self.generator = generator
        self.plan = MetadataFixPlan(plan_path or (settings.work_dir / "metadata_plan.json"))

    # ---- discovery -----------------------------------------------------

    def discover(self, *, video_ids: list[str] | None = None) -> list[PlanEntry]:
        with psycopg.connect(self.settings.database_url) as conn:
            rows = conn.execute(
                """
                SELECT video_id, title, description, published_at
                FROM youtube_videos
                WHERE is_current = TRUE
                ORDER BY published_at ASC
                """
            ).fetchall()

        entries: list[PlanEntry] = []
        for video_id, title, description, published_at in rows:
            if video_ids is not None and video_id not in video_ids:
                continue
            if not needs_metadata_fix(title or "", description or ""):
                continue
            existing = self.plan.existing(video_id)
            if existing is not None and existing.state != "pending":
                entries.append(existing)
                continue
            pub = published_at.date().isoformat() if published_at else ""
            entries.append(
                PlanEntry(
                    video_id=video_id,
                    old_title=title or "",
                    published_at=pub,
                    state="pending",
                    game=detect_game(title or ""),
                )
            )
            self.plan.upsert(entries[-1])
        return entries

    # ---- generation ----------------------------------------------------

    def generate_for(self, entry: PlanEntry) -> None:
        """Generate validated metadata for one plan entry and persist it on
        the entry. Raises ChannelMetadataError on generation/validation
        failure (the entry is then marked failed)."""
        try:
            if entry.game:
                generated = self.generator.generate(build_ai_context(entry.game))
            else:
                generated = self.generator.generate_archive_metadata(
                    entry.old_title, entry.published_at
                )
            validate_generated_metadata(generated.title, generated.description, generated.tags)
        except (ContentGenerationError, MetadataValidationError) as exc:
            entry.state = "failed"
            entry.detail = str(exc)
            self.plan.upsert(entry)
            raise ChannelMetadataError(f"{entry.video_id}: {exc}") from exc
        entry.new_title = generated.title
        entry.new_description = generated.description
        entry.new_tags = list(generated.tags)
        self.plan.upsert(entry)

    # ---- apply ----------------------------------------------------------

    def apply(
        self,
        *,
        max_updates: int | None = None,
        update_cost: int = _VIDEO_UPDATE_COST,
        quota_budget: int | None = None,
    ) -> tuple[int, int, list[tuple[str, str]]]:
        """Apply pending plan entries to YouTube. Stops when max_updates
        entries are applied or when quota_budget units are consumed (each
        videos().update costs `update_cost` units). Returns (applied,
        failed, failures). Resumes from the persisted plan on a re-run."""
        credentials = self.auth.load_credentials()
        channel = self.auth.fetch_channel_identity(credentials)
        expected = self.settings.youtube_expected_channel_id
        if expected and channel.channel_id != expected:
            raise ChannelMetadataError(
                f"authenticated channel {channel.channel_id} != expected {expected}"
            )
        youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)

        applied = 0
        failed: list[tuple[str, str]] = []
        for entry in self.plan.pending():
            if max_updates is not None and applied >= max_updates:
                break
            if quota_budget is not None and (applied + 1) * update_cost > quota_budget:
                break

            if entry.new_title is None:
                try:
                    self.generate_for(entry)
                except ChannelMetadataError as exc:
                    failed.append((entry.video_id, str(exc)))
                    continue
                if entry.new_title is None:
                    continue

            try:
                youtube.videos().update(
                    part="snippet",
                    body={
                        "id": entry.video_id,
                        "snippet": {
                            "title": entry.new_title,
                            "description": entry.new_description or "",
                            "tags": entry.new_tags,
                            "categoryId": self.settings.youtube_category_id,
                        },
                    },
                ).execute()
            except HttpError as exc:
                entry.state = "failed"
                entry.detail = f"update failed: {exc}"
                self.plan.upsert(entry)
                failed.append((entry.video_id, str(exc)))
                continue

            entry.state = "done"
            entry.detail = "applied"
            self.plan.upsert(entry)
            applied += 1

        return applied, len(failed), failed
