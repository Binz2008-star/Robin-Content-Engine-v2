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
# number is optional: omit it until a real per-series counter exists, so the
# queue job id is never published as a public episode number.
_SERIES_AR = "أرشيف روبنزو"
_SERIES_EN = "Robinzo Archive"
_METADATA_LANGUAGES = frozenset({"arabic", "english"})

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


def _with_episode_marker(title: str, marker: str) -> str:
    """Append an episode marker before #Shorts, within YouTube's 100 chars.

    The hook/descriptive part stays first; the marker goes at the end. A long
    title truncates the descriptive part and keeps both the marker and
    #Shorts.
    """
    if "#Shorts" in title:
        body = title[: title.rfind("#Shorts")].rstrip()
        suffix = " #Shorts"
    else:
        body, suffix = title, ""

    combined = f"{body} | {marker}{suffix}"
    if len(combined) <= _TITLE_MAX_LENGTH:
        return combined

    budget = _TITLE_MAX_LENGTH - len(marker) - len(suffix) - len(" | ") - 1
    if budget <= 0:
        return combined[: _TITLE_MAX_LENGTH - 1].rstrip() + "…"
    return f"{body[:budget].rstrip()}… | {marker}{suffix}"


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
    all series markings. `part` is optional and must be a real per-series
    counter when supplied; when omitted, no episode number is published, so
    the queue job id never leaks as a public part number.
    """
    normalized = language.strip().lower()
    if normalized not in _METADATA_LANGUAGES:
        raise ValueError("language must be 'arabic' or 'english'")
    english = normalized == "english"
    series_name = (
        series if series is not None else (_SERIES_EN if english else _SERIES_AR)
    ).strip()
    part_number = part
    if part_number is not None and part_number < 0:
        raise ValueError("part must be >= 0")

    game = (confirmed_game or "").strip() or None
    if game:
        templates = _EN_GAME_TITLES if english else _AR_GAME_TITLES
    else:
        templates = _EN_NEUTRAL_TITLES if english else _AR_NEUTRAL_TITLES
    title = templates[job_id % len(templates)].format(game=game or "")
    if len(title) > _TITLE_MAX_LENGTH:
        title = title[: _TITLE_MAX_LENGTH - 1].rstrip() + "…"
    if part_number is not None:
        marker = f"Part {part_number}" if english else f"الحلقة {part_number}"
        title = _with_episode_marker(title, marker)

    source_url = f"https://www.youtube.com/watch?v={source_video_id}"
    hashtags = ["#Shorts", "#gaming"] + ([_hashtag(game)] if game else [])
    if english:
        lines = [
            f"A {game} moment from the Robinzo archive." if game else
            "A moment from the Robinzo archive.",
        ]
        if series_name:
            series_line = f"📺 {series_name}"
            if part_number is not None:
                series_line += f" — Part {part_number}"
            lines.append(series_line)
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
            series_line = f"📺 {series_name}"
            if part_number is not None:
                series_line += f" — الحلقة {part_number}"
            lines.append(series_line)
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
