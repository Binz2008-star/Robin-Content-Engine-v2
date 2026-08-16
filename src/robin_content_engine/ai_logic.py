import json
import re

from openai import OpenAI
from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .models import GeneratedContent

# Matches the trailing timestamp that capture tooling appends to file names,
# e.g. "Fortnite   2026-08-15 22-20-30" or "Senua's Saga_ Hellblade 2 ...".
_TIMESTAMP_SUFFIX_RE = re.compile(r"\s+\d{4}-\d{2}-\d{2}\s+\d{2}-\d{2}-\d{2}\s*$")

# Phrases the metadata generator is explicitly forbidden from producing:
# deletion/fear clickbait, live-stream/tournament claims the AI cannot
# verify, and specific achievement claims. Any generated title/description
# containing one of these is rejected before it can reach YouTube.
CLICKBAIT_MARKERS: tuple[str, ...] = (
    "قبل الحذف",
    "ينحذف",
    "بث مباشر",
    "سحبنا بث",
    "بطولة",
    "مباراة",
    "الرقم القياسي",
    "فزنا",
    "أفضل لاعب",
)

_TITLE_MAX_LENGTH = 100
_DESCRIPTION_MAX_LENGTH = 5000
_TAG_MAX_COUNT = 20


class ContentGenerationError(RuntimeError):
    pass


class MetadataValidationError(RuntimeError):
    """Raised when AI-generated metadata fails the deterministic safety and
    bounds validation - the caller must not publish it."""


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


def validate_generated_metadata(
    title: str, description: str, tags: list[str]
) -> None:
    """Deterministic safety and bounds validation for AI-generated Arabic
    metadata, run BEFORE anything is written to YouTube. Rejects empty or
    oversized fields, title/description pairs shorter than the generated
    content model requires, and any banned clickbait/unverifiable-claim
    phrase. Raises MetadataValidationError with an explicit reason."""
    clean_title = " ".join(title.split()).strip()
    if not clean_title:
        raise MetadataValidationError("title is empty after normalization.")
    if len(clean_title) < 8 or len(clean_title) > _TITLE_MAX_LENGTH:
        raise MetadataValidationError(
            f"title length {len(clean_title)} outside [{8}, {_TITLE_MAX_LENGTH}]."
        )
    clean_description = " ".join(description.split()).strip()
    if not clean_description:
        raise MetadataValidationError("description is empty after normalization.")
    if len(clean_description) > _DESCRIPTION_MAX_LENGTH:
        raise MetadataValidationError(
            f"description exceeds {_DESCRIPTION_MAX_LENGTH} characters."
        )
    if len(tags) > _TAG_MAX_COUNT:
        raise MetadataValidationError(f"more than {_TAG_MAX_COUNT} tags.")
    for marker in CLICKBAIT_MARKERS:
        if marker in clean_title or marker in clean_description:
            raise MetadataValidationError(f"contains banned phrase {marker!r}.")


class ContentGenerator:
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=45.0)

    @staticmethod
    def _system_prompt(language: str) -> str:
        if language == "english":
            return (
                "You write YouTube Shorts metadata and voiceover scripts for a gaming "
                "channel (Robin Life & Gaming) that publishes original gameplay clips for "
                "a MIXED audience - UAE/Arabic gamers and international English-speaking "
                "viewers. Write in clear, natural, casual English that works for both - "
                "no heavy slang, no overly formal language.\n"
                "STRICT style rules:\n"
                "- Never use template openers like 'in this video, we showcase' or 'welcome "
                "back'.\n"
                "- Short, punchy, energetic. Vary the wording on EVERY video - never repeat "
                "the same sentence pattern between videos.\n"
                "- You cannot see the video: base everything only on the game name and the "
                "fact that it is original gameplay footage by Robin. NEVER invent specific "
                "in-game events, weapon names, characters, locations, or results. Describe "
                "the general experience only.\n"
                "- Never claim specific achievements, records, wins, kills, or results.\n"
                "- No clickbait ('watch before it's deleted'), no live-stream or tournament "
                "claims, no false promises. Do not copy other creators.\n"
                "- Titles: 5-9 words, exciting and clickable, must include the game name, "
                "8-100 characters, no timestamps.\n"
                "- Descriptions: 2-4 short casual lines with a light call to action plus "
                "3-5 hashtags that MIX English and Arabic (e.g. #Fortnite #فورتنايت) so "
                "both audiences find the video.\n"
                "- Return one JSON object only."
            )
        return (
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
        )

    @staticmethod
    def _game_user_prompt(video_context: str, language: str) -> str:
        if language == "english":
            fields = (
                '  "title": "short exciting English title with the game name, '
                "8-100 characters\",\n"
                '  "description": "casual English description for a mixed UAE + '
                "international audience, 2-4 short lines + mixed EN/AR hashtags, up to "
                "5000 characters\",\n"
                '  "tags": ["up to 15 relevant tags mixing English and Arabic, no # '
                'symbol"],\n'
                '  "script": "a natural spoken English voiceover for the short, roughly '
                "25-45 words, energetic live-commentary style, speaking as the player\""
            )
        else:
            fields = (
                '  "title": "short exciting Arabic title with the game name, '
                "8-100 characters\",\n"
                '  "description": "casual Gulf-Arabic description, 2-4 short lines '
                "+ hashtags, up to 5000 characters\",\n"
                '  "tags": ["up to 15 relevant Arabic tags, no # symbol"],\n'
                '  "script": "a natural spoken Gulf-Arabic voiceover for the short, '
                "roughly 25-45 words, energetic live-commentary style, speaking as "
                'the player"'
            )
        return (
            "Create metadata for this original gaming footage:\n"
            f"{video_context}\n\n"
            "Return exactly these fields:\n"
            "{\n" + fields + "\n}"
        )

    @staticmethod
    def _archive_system_prompt(language: str) -> str:
        if language == "english":
            return (
                "You write YouTube metadata for a gaming channel (Robin Life & Gaming) "
                "that serves a MIXED audience - UAE/Arabic gamers and international "
                "English-speaking viewers. These are OLD archive clips whose current "
                "titles are default or unclear. Write in clear, simple, neutral English "
                "that works for both audiences. You cannot see the video and do NOT know "
                "which game or subject it shows, so NEVER name a specific game, person, "
                "event, or claim specific content. Never use clickbait or false claims. "
                "Titles: short, 4-8 words. Descriptions: 1-3 short casual lines plus "
                "2-3 hashtags mixing English and Arabic. Return one JSON object only."
            )
        return (
            "You write YouTube metadata for an Arabic YouTube channel "
            "(Robin Life & Gaming). These are OLD archive clips whose current "
            "titles are default or unclear. Write in natural, casual Gulf/UAE "
            "Arabic. Keep it simple, truthful and general: you cannot see the "
            "video and do NOT know which game or subject it shows, so NEVER "
            "name a specific game, person, event, or claim specific content. "
            "Never use clickbait or false claims. Titles: short, 4-8 words. "
            "Descriptions: 1-3 short casual lines plus 2-3 hashtags. Return "
            "one JSON object only."
        )

    @staticmethod
    def _archive_user_prompt(old_title: str, published_at: str, language: str) -> str:
        if language == "english":
            fields = (
                '  "title": "short neutral English title, 8-100 characters",\n'
                '  "description": "neutral English description for a mixed UAE + '
                "international audience, 1-3 short lines + mixed EN/AR hashtags, up to "
                "5000 characters\",\n"
                '  "tags": ["up to 10 relevant tags mixing English and Arabic, no # '
                'symbol"],\n'
                '  "script": "a short neutral English sentence, at least 25 characters '
                "(not used for archive videos but must be non-empty)\""
            )
        else:
            fields = (
                '  "title": "short neutral Arabic title, 8-100 characters",\n'
                '  "description": "neutral Arabic description, 1-3 short lines + '
                "hashtags, up to 5000 characters\",\n"
                '  "tags": ["up to 10 relevant Arabic tags, no # symbol"],\n'
                '  "script": "a short neutral Arabic sentence, at least 25 '
                "characters (not used for archive videos but must be non-empty)\""
            )
        return (
            f"Current title: {old_title}\n"
            f"Published: {published_at}\n\n"
            "Return exactly:\n"
            "{\n" + fields + "\n}"
        )

    def _complete(self, messages: list[dict[str, str]]) -> GeneratedContent:
        response = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            temperature=0.85,
            messages=messages,
        )
        raw = response.choices[0].message.content
        if not raw:
            raise ContentGenerationError("DeepSeek returned an empty response")
        try:
            generated = GeneratedContent.model_validate(json.loads(raw))
        except (ValidationError, TypeError, KeyError) as exc:
            raise ContentGenerationError(f"Invalid generated metadata: {exc}") from exc
        try:
            validate_generated_metadata(generated.title, generated.description, generated.tags)
        except MetadataValidationError as exc:
            raise ContentGenerationError(f"Unsafe generated metadata: {exc}") from exc
        return generated

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((ContentGenerationError, json.JSONDecodeError)),
        reraise=True,
    )
    def generate(self, video_context: str, language: str = "arabic") -> GeneratedContent:
        """Generate gaming metadata. `language` is 'arabic' (Gulf Arabic, the
        default) or 'english' (clear English aimed at a mixed UAE/AE +
        international audience, with mixed EN/AR hashtags)."""
        messages = [
            {"role": "system", "content": self._system_prompt(language)},
            {"role": "user", "content": self._game_user_prompt(video_context, language)},
        ]
        return self._complete(messages)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((ContentGenerationError, json.JSONDecodeError)),
        reraise=True,
    )
    def generate_archive_metadata(
        self, old_title: str, published_at: str, language: str = "arabic"
    ) -> GeneratedContent:
        """Generate metadata for an OLD archive video whose original title is
        default/junk and whose content cannot be seen. The prompt is forced
        to stay neutral - it never names a game, person, or event it cannot
        verify, so an unknown-content clip is never mislabeled."""
        messages = [
            {"role": "system", "content": self._archive_system_prompt(language)},
            {
                "role": "user",
                "content": self._archive_user_prompt(old_title, published_at, language),
            },
        ]
        return self._complete(messages)
