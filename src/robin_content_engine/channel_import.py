from __future__ import annotations

from pathlib import Path
from typing import Any

import imageio_ffmpeg
import psycopg

from .channel_metadata import detect_game
from .clip_selector import WindowSelectorConfig
from .config import Settings
from .database import JobRepository
from .production_runner import ProductionRunError, run_production


class ChannelImportError(RuntimeError):
    pass


def _ffmpeg_location() -> str | None:
    """yt-dlp accepts either a directory containing ffmpeg(.exe) or the
    full path to the binary. imageio_ffmpeg's bundled binary is named with
    its platform/version suffix (e.g. ffmpeg-win-x86_64-v7.1.exe), so the
    full path must be passed - its parent directory alone would not be
    found by yt-dlp's default ffmpeg/ffprobe name lookup."""
    try:
        return str(Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve())
    except Exception:
        return None


def download_channel_video(video_id: str, dest_dir: Path) -> Path:
    """Download a (public, own-channel) video from YouTube to
    dest_dir/<video_id>.mp4 using yt-dlp. Requires the optional yt-dlp
    dependency. Raises ChannelImportError on any failure."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise ChannelImportError(
            "yt-dlp is required to download videos from the channel. "
            "Install it with: pip install yt-dlp"
        ) from exc

    dest_dir.mkdir(parents=True, exist_ok=True)
    output_path = dest_dir / f"{video_id}.mp4"
    if output_path.is_file() and output_path.stat().st_size > 0:
        return output_path

    opts: dict[str, Any] = {
        "outtmpl": str(dest_dir / f"{video_id}.%(ext)s"),
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        # The "android" player client does not require browser cookies /
        # PO tokens and reliably yields a plain mp4 stream for public
        # videos (tested against this channel's own uploads).
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    ffmpeg_location = _ffmpeg_location()
    if ffmpeg_location:
        opts["ffmpeg_location"] = ffmpeg_location

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
    except Exception as exc:
        raise ChannelImportError(f"download failed for {video_id}: {exc}") from exc

    if not output_path.is_file():
        candidates = sorted(dest_dir.glob(f"{video_id}.*"))
        if not candidates:
            raise ChannelImportError(f"download of {video_id} produced no output file.")
        output_path = candidates[0]
    if output_path.stat().st_size == 0:
        raise ChannelImportError(f"downloaded file for {video_id} is empty.")
    return output_path


def fetch_video_title(settings: Settings, video_id: str) -> str:
    """Look up the video title from the stored channel snapshot, if present."""
    try:
        with psycopg.connect(settings.database_url) as conn:
            row = conn.execute(
                "SELECT title FROM youtube_videos WHERE video_id = %s",
                (video_id,),
            ).fetchone()
            if row and row[0]:
                return str(row[0])
    except Exception:
        pass
    return f"Channel video {video_id}"


def list_long_videos(
    settings: Settings, *, min_seconds: int = 60, limit: int | None = None
) -> list[dict[str, Any]]:
    """List the channel's long-form (non-Short) videos from the stored
    snapshot, newest first, as import candidates for Short extraction."""
    with psycopg.connect(settings.database_url) as conn:
        sql = (
            "SELECT video_id, title, published_at, duration_seconds, view_count "
            "FROM youtube_videos "
            "WHERE is_current = TRUE AND duration_seconds IS NOT NULL "
            "AND duration_seconds >= %s "
            "ORDER BY published_at DESC"
        )
        params: list[Any] = [min_seconds]
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "video_id": r[0],
            "title": r[1],
            "published_at": r[2].isoformat() if r[2] else None,
            "duration_seconds": int(r[3]),
            "view_count": int(r[4]) if r[4] is not None else None,
        }
        for r in rows
    ]


def import_video_as_short(
    video_id: str,
    repository: JobRepository,
    settings: Settings,
    *,
    rank: int = 1,
    model_size: str = "base",
    horizontal_offset_ratio: float = 0.5,
    package_dest_root: Path | None = None,
    selector_config: WindowSelectorConfig | None = None,
) -> tuple[int, Any]:
    """Download one own-channel video, register it as a rights-confirmed
    local job (it is the channel's own upload), run it through the full
    production pipeline (highlight analysis + reframe + captions + quality
    gate + package) and return (job_id, ProductionRunResult).

    The job is registered with rights_confirmed=TRUE and a rights note
    recording the source upload, so the existing production machinery
    treats it exactly like an operator-confirmed local capture. Returns
    before any publishing - the caller decides whether/when to upload.

    Idempotent: re-running for the same video_id reuses the existing
    pending job instead of registering a duplicate (and re-cutting with
    the current window config produces a fresh, longer artifact if the
    bounds changed)."""
    source_title = _normalized_import_title(settings, video_id)

    downloads = settings.work_dir / "downloads"
    video_path = download_channel_video(video_id, downloads)

    job_id = _existing_pending_job_id(settings, video_id)
    if job_id is None:
        rights_note = (
            f"Imported from the channel's own upload {video_id} on "
            "https://www.youtube.com/watch?v="
            f"{video_id}. Robin owns this footage; it was published on the "
            "Robin Life & Gaming channel."
        )
        with repository.running():
            job_id = repository.enqueue_local(video_path, source_title, rights_note)

    try:
        # run_production() internally uses its own `with repository.running():`
        # block, and psycopg_pool cannot reopen a pool that was already
        # opened AND closed - so it needs a FRESH JobRepository, never the
        # one used for the enqueue above (its pool is now closed).
        pipeline_repository = JobRepository(settings.database_url, settings.max_job_attempts)
        result = run_production(
            job_id,
            rank,
            pipeline_repository,
            settings,
            horizontal_offset_ratio=horizontal_offset_ratio,
            model_size=model_size,
            package_dest_root=package_dest_root,
            selector_config=selector_config,
        )
    except ProductionRunError as exc:
        raise ChannelImportError(f"production pipeline failed for job {job_id}: {exc}") from exc
    return job_id, result


def _normalized_import_title(settings: Settings, video_id: str) -> str:
    """A clean, truthful source title for an imported Short.

    The stored channel snapshot can carry default/junk capture names
    ("Apexsf.kjh", "Black ops", "Furniture"...) that must NEVER drive the
    Short's metadata. When the conservative game detector recognizes a real
    game, use "<Game> gameplay"; otherwise use a neutral archive label so
    the AI metadata cannot mislabel the clip."""
    title = fetch_video_title(settings, video_id)
    game = detect_game(title)
    if game:
        return f"{game} gameplay"
    if title and not title.startswith("Channel video"):
        return "Archived gameplay"
    return f"Channel video {video_id}"


def _existing_pending_job_id(settings: Settings, video_id: str) -> int | None:
    """Find a not-yet-uploaded queue job that already imports this video, so
    a re-run never registers a duplicate."""
    with psycopg.connect(settings.database_url) as conn:
        row = conn.execute(
            """
            SELECT id FROM video_queue
            WHERE rights_note LIKE %s
              AND status IN ('pending', 'processing', 'rendered')
              AND (youtube_id IS NULL OR youtube_id = '')
            ORDER BY id
            LIMIT 1
            """,
            (f"%{video_id}%",),
        ).fetchone()
    return int(row[0]) if row else None
