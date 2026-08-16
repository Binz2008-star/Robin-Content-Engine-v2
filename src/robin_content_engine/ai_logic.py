import json
import re

from openai import OpenAI
from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .models import GeneratedContent

# Matches the trailing timestamp that capture tooling appends to file names,
# e.g. "Fortnite   2026-08-15 22-20-30" or "Senua's Saga_ Hellblade 2 ...".
_TIMESTAMP_SUFFIX_RE = re.compile(r"\s+\d{4}-\d{2}-\d{2}\s+\d{2}-\d{2}-\d{2}\s*$")


class ContentGenerationError(RuntimeError):
    pass


def extract_game_name(source_title: str) -> str:
    """Best-effort, deterministic game-name extraction from a capture
    file's source title. Pure string logic - never a network call. Used to
    give the metadata generator the game without the recording timestamp."""
    game = _TIMESTAMP_SUFFIX_RE.sub("", source_title.strip())
    game = game.replace("_", " ").strip()
    return game or source_title.strip()


def build_ai_context(source_title: str) -> str:
    """Deterministic context block handed to the metadata generator. Tells
    it the game and that the footage is original and operator-owned so it
    stays truthful (it never sees the video itself)."""
    game = extract_game_name(source_title)
    return (
        f"Game: {game}\n"
        f"Source title: {source_title}\n"
        "This is ORIGINAL gameplay footage recorded by Robin for the "
        "Robin Life & Gaming Arabic gaming channel. Robin owns the footage "
        "and has the right to publish it. You cannot see the actual video "
        "content."
    )


class ContentGenerator:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=45.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((ContentGenerationError, json.JSONDecodeError)),
        reraise=True,
    )
    def generate(self, video_context: str) -> GeneratedContent:
        response = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            temperature=0.85,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write YouTube Shorts metadata and voiceover scripts for an "
                        "Arabic gaming channel (Robin Life & Gaming) that publishes original "
                        "gameplay clips. Write in natural, casual Gulf/UAE Arabic - exactly "
                        "how a young Gulf gamer talks with friends, NOT formal news Arabic, "
                        "NOT ChatGPT-sounding Arabic.\n"
                        "STRICT style rules:\n"
                        "- Never use stiff or template phrases like: 'في هذا الفيديو، "
                        "نستعرض', 'نأخذكم في جولة', 'نقدم لكم', 'نعيش أجواء', 'تابعونا "
                        "لاكتشاف', 'مرحباً بكم', 'أهلاً بكم'. Never start with 'في هذا "
                        "الفيديو'.\n"
                        "- Short, punchy, energetic. Vary the wording on EVERY video - "
                        "never repeat the same sentence pattern between videos.\n"
                        "- You cannot see the video: base everything only on the game name "
                        "and the fact that it is original gameplay footage by Robin. NEVER "
                        "invent specific in-game events, weapon names, characters, "
                        "locations, or results. Describe the general experience only.\n"
                        "- Never claim specific achievements, records, wins, kills, or "
                        "results (no 'حطمنا الرقم القياسي', no 'فزنا', no counts).\n"
                        "- Never use deletion/fear clickbait like 'شاهد قبل الحذف', 'قبل "
                        "ما ينحذف', or anything implying the video will disappear.\n"
                        "- Never claim it is a live stream ('بث مباشر', 'سحبنا بث'), a "
                        "tournament or match ('بطولة', 'مباراة'), or any other event you "
                        "cannot verify.\n"
                        "- Do not copy other creators. Do not make false or unverifiable "
                        "claims (no 'أفضل لاعب', no guaranteed wins, no promised rewards).\n"
                        "- Titles: 5-9 words, exciting and clickable, must include the game "
                        "name, 8-100 characters, no timestamps.\n"
                        "- Descriptions: 2-4 short casual lines with a light call to action "
                        "plus 3-5 hashtag lines (hashtags also written in Arabic).\n"
                        "- Return one JSON object only."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Create metadata for this original gaming footage:\n"
                        f"{video_context}\n\n"
                        "Return exactly these fields:\n"
                        "{\n"
                        '  "title": "short exciting Arabic title with the game name, '
                        '8-100 characters",\n'
                        '  "description": "casual Gulf-Arabic description, 2-4 short lines '
                        '+ hashtags, up to 5000 characters",\n'
                        '  "tags": ["up to 15 relevant Arabic tags, no # symbol"],\n'
                        '  "script": "a natural spoken Gulf-Arabic voiceover for the short, '
                        'roughly 25-45 words, energetic live-commentary style, speaking as '
                        'the player"'
                        "\n}"
                    ),
                },
            ],
        )

        raw = response.choices[0].message.content
        if not raw:
            raise ContentGenerationError("DeepSeek returned an empty response")

        try:
            return GeneratedContent.model_validate(json.loads(raw))
        except (ValidationError, TypeError, KeyError) as exc:
            raise ContentGenerationError(f"Invalid generated metadata: {exc}") from exc
