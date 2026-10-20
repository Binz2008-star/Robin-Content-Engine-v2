"""Deterministic YouTube metadata for cloud-runner Shorts - no AI, no network.

The owner chose not to use an LLM for titles (2026-10-01). The previous
no-AI fallback gave every Short the same English title ("Archived gameplay
— Highlight"), which repeats the channel's duplicate-title problem. This
module builds varied, truthful Arabic (or English) metadata instead:

- the title rotates over a few templates, chosen by the queue job id, so
  consecutive Shorts do not share a title;
- a stable series label and a part number prefix the title and appear in the
  description, so the channel reads as an ordered series;
- a game is named ONLY when the caller passes a confirmed game (the drive
  runner confirms games from PlayStation's own share tags); otherwise the
  title stays neutral;
- the description links back to the full source video on the channel, so
  a Short can send viewers to the long video it was cut from.

Templates are generic on purpose: they never describe what happens in the
clip (a kill, a win), because nothing here has looked at the frames.
"""

from __future__ import annotations

_TITLE_MAX_LENGTH = 100

# The stable series label used when the caller does not supply one. The part
# number defaults to the queue job id: it is deterministic and available
# without a schema change, and callers may pass a clean per-series counter
# later. A leading zero is not used; the id is shown as-is.
_SERIES_AR = "أرشيف روبنزو"
_SERIES_EN = "Robinzo Archive"

_AR_GAME_TITLES: tuple[str, ...] = (
    "{game} | لحظة نار 🔥 #Shorts",
    "شوف هاللقطة في {game} 😳 #Shorts",
    "{game}: لقطة ما بتتفوت 🎮 #Shorts",
    "من أرشيف روبنزو | {game} 🔥 #Shorts",
    "لقطة {game} من جلسة قديمة 👀 #Shorts",
    "{game} مع روبنزو 🎯 #Shorts",
)
_AR_NEUTRAL_TITLES: tuple[str, ...] = (
    "لقطة نار من أرشيف روبنزو 🔥 #Shorts",
    "شوف هاللقطة من جلسة قديمة 😳 #Shorts",
    "لحظة من أرشيف القناة 🎮 #Shorts",
    "من أرشيف روبنزو | لقطة قوية 👀 #Shorts",
    "جيمنغ مع روبنزو 🎯 #Shorts",
)
_EN_GAME_TITLES: tuple[str, ...] = (
    "{game} | Don't miss this 🔥 #Shorts",
    "{game} moment from the archive 🎮 #Shorts",
    "Watch this {game} clip 😳 #Shorts",
    "{game} with Robinzo 🎯 #Shorts",
)
_EN_NEUTRAL_TITLES: tuple[str, ...] = (
    "Gameplay moment from the Robinzo archive 🔥 #Shorts",
    "Watch this clip from an old session 😳 #Shorts",
    "From the channel archive 🎮 #Shorts",
    "Gaming with Robinzo 🎯 #Shorts",
)


def _hashtag(game: str) -> str:
    return "#" + "".join(ch for ch in game if ch.isalnum())


def _fit_series_title(prefix: str, title: str) -> str:
    """Join a series prefix and a template title within YouTube's 100 chars.

    Keeps the trailing `#Shorts` tag when the base title has one, so a long
    series prefix truncates the descriptive part instead of dropping the tag.
    """
    combined = f"{prefix}{title}"
    if len(combined) <= _TITLE_MAX_LENGTH:
        return combined

    suffix = " #Shorts" if "#Shorts" in title else ""
    body = title[: title.rfind("#Shorts")].rstrip() if suffix else title
    budget = _TITLE_MAX_LENGTH - len(prefix) - len(suffix) - 1
    if budget <= 0:
        return combined[: _TITLE_MAX_LENGTH - 1].rstrip() + "…"
    return f"{prefix}{body[:budget].rstrip()}…{suffix}"


def drive_short_metadata(
    *,
    job_id: int,
    source_video_id: str,
    confirmed_game: str | None,
    language: str = "arabic",
    series: str | None = None,
    part: int | None = None,
) -> tuple[str, str, list[str]]:
    """(title, description, tags) for one cloud-runner Short.

    `series` defaults to the channel's archive label; an empty string omits
    all series markings. `part` defaults to `job_id` (deterministic, no
    schema change) and may be overridden by a caller that keeps its own
    per-series counter.
    """
    english = language.strip().lower() == "english"
    series_name = (
        series if series is not None else (_SERIES_EN if english else _SERIES_AR)
    ).strip()
    part_number = job_id if part is None else part
    if part_number < 0:
        raise ValueError("part must be >= 0")

    game = (confirmed_game or "").strip() or None
    if game:
        templates = _EN_GAME_TITLES if english else _AR_GAME_TITLES
    else:
        templates = _EN_NEUTRAL_TITLES if english else _AR_NEUTRAL_TITLES
    title = templates[job_id % len(templates)].format(game=game or "")
    if len(title) > _TITLE_MAX_LENGTH:
        title = title[: _TITLE_MAX_LENGTH - 1].rstrip() + "…"
    if series_name:
        title = _fit_series_title(f"{series_name} #{part_number} | ", title)

    source_url = f"https://www.youtube.com/watch?v={source_video_id}"
    hashtags = ["#Shorts", "#gaming"] + ([_hashtag(game)] if game else [])
    if english:
        lines = [
            f"A {game} moment from the Robinzo archive." if game else
            "A moment from the Robinzo archive.",
        ]
        if series_name:
            lines.append(f"📺 {series_name} — Part {part_number}")
        lines.extend(
            [
                f"🎬 Full video: {source_url}",
                "🔔 Subscribe so you don't miss the next one!",
            ]
        )
    else:
        lines = [
            f"لقطة {game} من أرشيف روبنزو." if game else "لقطة من أرشيف روبنزو.",
        ]
        if series_name:
            lines.append(f"📺 {series_name} — الحلقة {part_number}")
        lines.extend(
            [
                f"🎬 الفيديو الكامل: {source_url}",
                "🔔 اشترك بالقناة عشان ما يفوتك الجاي!",
            ]
        )
    description = "\n".join(lines) + "\n\n" + " ".join(hashtags)

    tags = ["Robinzo", "gaming", "shorts", "العاب", "جيمنغ"]
    if game:
        tags.insert(0, game)
    return title, description, tags
