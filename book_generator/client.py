"""Model client with fallback chain and retry logic.

Two client types:
  aoai    — AzureOpenAI (for gpt-4o / gpt-4o-mini via Azure OpenAI service)
  foundry — OpenAI-compatible client (for serverless Foundry models: Llama, Mistral)
            Each serverless model has its own unique endpoint URL in Foundry.

Tries models in priority order. Retries up to MAX_RETRIES times with
exponential backoff before falling through to the next model.
"""
import os
import time
import random
from urllib.parse import urlparse, parse_qs

from openai import AzureOpenAI, OpenAI, RateLimitError, APIStatusError, APIConnectionError
from rich.console import Console

console = Console()

# kind        : "aoai" uses AzureOpenAI; "foundry" uses OpenAI with a custom base_url
# endpoint_var: env var holding the endpoint URL
# key_var     : env var holding the API key
_MODEL_CONFIGS = {
    "gpt-4o":                       ("aoai",    "AZURE_OPENAI_ENDPOINT",  "AZURE_OPENAI_KEY"),

    "Llama-3.3-70B-Instruct":        ("foundry", "AZURE_LLAMA_ENDPOINT",   "AZURE_LLAMA_KEY"),
    "Mistral-Large-3":              ("foundry", "AZURE_MISTRAL_ENDPOINT",  "AZURE_MISTRAL_KEY"),
    "Phi-4":                        ("foundry", "AZURE_PHI4_ENDPOINT",     "AZURE_PHI4_KEY"),
}

MAX_RETRIES = 3
BASE_DELAY_S = 4

_REFUSAL_PHRASES = (
    "i can't do that",
    "i cannot do that",
    "i'm not able to",
    "i am not able to",
    "i'm unable to",
    "i am unable to",
    "i apologize, but",
    "how about i summarize",
    "instead, i can",
    "instead i can",
    "not in the public domain",
    "still under copyright",
)


def _foundry_base_url(endpoint: str) -> tuple[str, str | None]:
    """Normalise a Foundry endpoint URL.

    Handles both endpoint styles from the Azure AI Foundry portal:
      Old per-model:  https://host.region.models.ai.azure.com[/v1][/chat/completions]
      New unified:    https://project.services.ai.azure.com/models[/chat/completions][?api-version=...]

    Returns (base_url, api_version) where api_version may be None.
    For old-style endpoints the base_url ends in /v1 (OpenAI convention).
    For new unified endpoints the base_url ends in /models (no /v1).
    """
    parsed = urlparse(endpoint)
    path = parsed.path.rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]

    api_version = parse_qs(parsed.query).get("api-version", [None])[0]

    # New unified endpoint — base is scheme://host/models (no /v1)
    if parsed.netloc.endswith(".services.ai.azure.com"):
        base = f"{parsed.scheme}://{parsed.netloc}{path}"
        return base, api_version

    # Old per-model serverless endpoint — must end in /v1
    if not path.endswith("/v1"):
        path += "/v1"
    return f"{parsed.scheme}://{parsed.netloc}{path}", api_version


class ContentFilterError(Exception):
    """Raised when a prompt is rejected by a content/safety filter.

    The chain will fall through to the next model — different models have
    different filter sensitivity levels.
    """


def _is_content_filter(e: "APIStatusError") -> bool:
    msg = str(e.message).lower()
    return e.status_code == 400 and (
        "content_filter" in msg
        or "content management policy" in msg
        or "responsibleaipolicyviolation" in msg
    )


def _is_refusal(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in _REFUSAL_PHRASES)


class ModelClient:
    def __init__(self, model_config: dict):
        names = [model_config["primary"]] + model_config.get("fallback", [])
        self.models = [n for n in names if n in _MODEL_CONFIGS]
        unknown = [n for n in names if n not in _MODEL_CONFIGS]
        if unknown:
            console.print(f"[yellow]Warning: unknown model(s) in config: {unknown}[/yellow]")

    def complete(self, messages: list[dict], **kwargs) -> str:
        """Send messages to the first available model; fall back on failure."""
        for name in self.models:
            kind, endpoint_var, key_var = _MODEL_CONFIGS[name]
            endpoint = os.getenv(endpoint_var)
            key = os.getenv(key_var)
            if not endpoint or not key:
                console.print(f"  [dim]Skipping {name}: {endpoint_var} / {key_var} not set[/dim]")
                continue
            try:
                result = self._try_model(name, kind, endpoint, key, messages, **kwargs)
            except ContentFilterError:
                console.print(f"  [yellow]Falling through from {name} (content filter) to next model[/yellow]")
                continue  # try next model — different models have different filter sensitivity
            if result is not None:
                return result
            console.print(f"  [yellow]Falling through from {name} to next model[/yellow]")
        raise RuntimeError("All models exhausted — check your .env endpoint/key values.")

    def _make_client(self, kind: str, endpoint: str, key: str):
        if kind == "aoai":
            api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
            return AzureOpenAI(azure_endpoint=endpoint, api_key=key, api_version=api_version)
        else:
            base_url, api_version = _foundry_base_url(endpoint)
            extra = {"api-version": api_version} if api_version else {}
            return OpenAI(base_url=base_url, api_key=key, default_query=extra)

    def _try_model(self, name, kind, endpoint, key, messages, **kwargs) -> str | None:
        client = self._make_client(kind, endpoint, key)
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = client.chat.completions.create(model=name, messages=messages, **kwargs)
                content = resp.choices[0].message.content
                if not content:
                    console.print(f"  [yellow]{name} returned empty content (content filter?) — trying next model[/yellow]")
                    return None
                if _is_refusal(content):
                    console.print(f"  [yellow]{name} refused — trying next model[/yellow]")
                    return None
                return content
            except RateLimitError:
                delay = BASE_DELAY_S * (2 ** attempt) + random.uniform(0, 2)
                console.print(
                    f"  [yellow]{name} rate-limited, waiting {delay:.1f}s "
                    f"[{attempt}/{MAX_RETRIES}][/yellow]"
                )
                time.sleep(delay)
            except APIStatusError as e:
                if e.status_code in (500, 502, 503):
                    delay = BASE_DELAY_S * attempt + random.uniform(0, 1)
                    console.print(
                        f"  [yellow]{name} server error ({e.status_code}), "
                        f"retrying in {delay:.1f}s [{attempt}/{MAX_RETRIES}][/yellow]"
                    )
                    time.sleep(delay)
                else:
                    if _is_content_filter(e):
                        console.print(f"  [red]{name} content filter — prompt blocked, trying next model[/red]")
                        raise ContentFilterError(str(e.message))
                    console.print(f"  [red]{name} HTTP {e.status_code}: {e.message}[/red]")
                    if e.status_code == 404:
                        kind, endpoint_var, _ = _MODEL_CONFIGS[name]
                        if kind == "foundry":
                            raw = os.getenv(endpoint_var, "")
                            base, ver = _foundry_base_url(raw)
                            console.print(f"  [dim]  → resolved base_url: {base} (api-version: {ver})[/dim]")
                    return None  # Don't retry 4xx (except 429 → RateLimitError above)
            except APIConnectionError as e:
                delay = BASE_DELAY_S * attempt
                console.print(
                    f"  [yellow]{name} connection error: {e}, "
                    f"retrying in {delay}s [{attempt}/{MAX_RETRIES}][/yellow]"
                )
                time.sleep(delay)
            except Exception as e:
                console.print(f"  [red]{name} unexpected error: {e}[/red]")
                return None
        return None
