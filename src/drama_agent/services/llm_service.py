from openai import AsyncOpenAI
from drama_agent.config import settings
import json
import re


# Model prefix → (api_key_attr, base_url_attr)
_MODEL_ROUTING: list[tuple[str, str, str]] = [
    ("kimi-",           "kimi_api_key",       "kimi_base_url"),
    ("glm-",            "glm_api_key",        "glm_base_url"),
    ("minimax-",        "minimax_api_key",    "minimax_base_url"),
]


def _resolve_client(model: str) -> tuple[AsyncOpenAI, str]:
    """Return (AsyncOpenAI client, actual_model_name) for the given model string."""
    # Check drama custom endpoint first (exact match on drama_text_model)
    if settings.drama_text_model and model == settings.drama_text_model:
        api_key = settings.drama_api_key or "placeholder"
        client = AsyncOpenAI(api_key=api_key, base_url=settings.drama_base_url or None)
        return client, model

    lower = model.lower()
    for prefix, key_attr, url_attr in _MODEL_ROUTING:
        if lower.startswith(prefix):
            api_key = getattr(settings, key_attr, "") or "placeholder"
            base_url = getattr(settings, url_attr, "")
            client = AsyncOpenAI(api_key=api_key, base_url=base_url or None)
            return client, model

    # Fallback: use drama endpoint
    api_key = settings.drama_api_key or "placeholder"
    client = AsyncOpenAI(api_key=api_key, base_url=settings.drama_base_url or None)
    return client, model


class LLMService:
    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.7,
        model: str | None = None,
    ) -> str:
        """Simple completion returning text. Uses per-call model routing."""
        if not model:
            raise ValueError("model must be specified")
        client, actual_model = _resolve_client(model)

        kwargs: dict = dict(
            model=actual_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=8000,
        )

        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    async def complete_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
        model: str | None = None,
    ) -> dict:
        """Completion that parses JSON response, stripping any markdown fences."""
        system_with_json = (
            system + "\n\nRespond ONLY with valid JSON. No markdown, no explanation."
        )
        text = await self.complete(system_with_json, user, temperature=temperature, model=model)
        return self._parse_json(text)

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = text.strip()
        fence = re.match(r"^```(?:json)?\s*\n?([\s\S]*?)\n?```$", text)
        if fence:
            text = fence.group(1).strip()
        start = min(
            (text.find(c) for c in ('{', '[') if text.find(c) != -1),
            default=0,
        )
        end_brace = text.rfind('}')
        end_bracket = text.rfind(']')
        end = max(end_brace, end_bracket) + 1
        if end > start:
            text = text[start:end]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}


llm_service = LLMService()
