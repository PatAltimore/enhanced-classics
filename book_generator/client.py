"""Model client with fallback chain and retry logic.

Tries models in priority order. For each model, retries up to MAX_RETRIES
times with exponential backoff before falling through to the next model.
"""
import os
import time
import random
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from rich.console import Console

console = Console()

# Maps model names to their endpoint/key environment variable names.
# Azure OpenAI models share one endpoint; Foundry serverless models share another.
_ENDPOINT_MAP = {
    "gpt-4o":                            ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY"),
    "gpt-4o-mini":                       ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_KEY"),
    "Meta-Llama-3.3-70B-Instruct":       ("AZURE_FOUNDRY_ENDPOINT", "AZURE_FOUNDRY_KEY"),
    "Mistral-Large-3":                   ("AZURE_FOUNDRY_ENDPOINT", "AZURE_FOUNDRY_KEY"),
}

MAX_RETRIES = 3
BASE_DELAY_S = 4


class ModelClient:
    def __init__(self, model_config: dict):
        """model_config: {"primary": "gpt-4.1", "fallback": [...]}"""
        names = [model_config["primary"]] + model_config.get("fallback", [])
        self.models = [n for n in names if n in _ENDPOINT_MAP]
        unknown = [n for n in names if n not in _ENDPOINT_MAP]
        if unknown:
            console.print(f"[yellow]Warning: unknown model(s) in config: {unknown}[/yellow]")

    def complete(self, messages: list, **kwargs) -> str:
        """Send messages to the first available model; fall back on failure."""
        last_error = None
        for model_name in self.models:
            endpoint_var, key_var = _ENDPOINT_MAP[model_name]
            endpoint = os.getenv(endpoint_var)
            key = os.getenv(key_var)

            if not endpoint or not key:
                console.print(
                    f"  [dim]Skipping {model_name}: {endpoint_var} / {key_var} not set[/dim]"
                )
                continue

            result = self._try_model(model_name, endpoint, key, messages, **kwargs)
            if result is not None:
                return result

            console.print(f"  [yellow]Falling through from {model_name} to next model[/yellow]")

        raise RuntimeError(
            f"All models exhausted. Last error: {last_error}\n"
            "Check that AZURE_OPENAI_ENDPOINT/KEY and AZURE_FOUNDRY_ENDPOINT/KEY are set."
        )

    def _try_model(self, name: str, endpoint: str, key: str, messages: list, **kwargs) -> str | None:
        client = ChatCompletionsClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(key),
        )
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.complete(model=name, messages=messages, **kwargs)
                return response.choices[0].message.content
            except HttpResponseError as e:
                if e.status_code == 429:
                    delay = BASE_DELAY_S * (2 ** attempt) + random.uniform(0, 2)
                    console.print(
                        f"  [yellow]{name} rate-limited (429), waiting {delay:.1f}s "
                        f"[attempt {attempt}/{MAX_RETRIES}][/yellow]"
                    )
                    time.sleep(delay)
                elif e.status_code in (500, 502, 503):
                    delay = BASE_DELAY_S * attempt + random.uniform(0, 1)
                    console.print(
                        f"  [yellow]{name} server error ({e.status_code}), retrying in {delay:.1f}s "
                        f"[attempt {attempt}/{MAX_RETRIES}][/yellow]"
                    )
                    time.sleep(delay)
                else:
                    console.print(f"  [red]{name} HTTP {e.status_code}: {e.message}[/red]")
                    return None  # Don't retry 4xx errors other than 429
            except Exception as e:
                delay = BASE_DELAY_S * attempt
                console.print(
                    f"  [yellow]{name} error: {e}, retrying in {delay}s "
                    f"[attempt {attempt}/{MAX_RETRIES}][/yellow]"
                )
                time.sleep(delay)
        return None
