import json

from openai import OpenAI
from pydantic import ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .models import GeneratedContent


class ContentGenerationError(RuntimeError):
    pass


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
            temperature=0.7,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You create metadata and an original short Arabic voiceover "
                        "for gaming videos. Use clear Gulf/UAE-friendly Arabic without "
                        "pretending to be a specific person. Do not copy lyrics, scripts, "
                        "titles, or descriptions from other creators. Do not make "
                        "unverifiable claims. Return one JSON object only."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Create metadata for this original or licensed gaming footage:\n"
                        f"{video_context}\n\n"
                        "Return exactly these fields:\n"
                        "{\n"
                        '  "title": "8-100 characters",\n'
                        '  "description": "useful Arabic description, up to 5000 characters",\n'
                        '  "tags": ["up to 20 relevant tags without #"],\n'
                        '  "script": "an original energetic voiceover, roughly 20-45 seconds"\n'
                        "}"
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
