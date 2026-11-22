import asyncio
import http.client
import json
import os
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from .security import MAX_BODY, redact, request_json

PROVIDERS = ("offline", "ollama", "openai")
MODEL = re.compile(r"^[A-Za-z0-9._:/-]{1,120}$")


def models_from_env(name):
    result = tuple(dict.fromkeys(value.strip() for value in os.getenv(name, "").split(",") if value.strip()))
    if len(result) > 30 or any(not MODEL.fullmatch(model) for model in result):
        raise ValueError("AI model list contains an invalid model identifier")
    return result


@dataclass(frozen=True)
class AISettings:
    ollama_models: tuple[str, ...] = ()
    openai_models: tuple[str, ...] = ()
    openai_url: str = ""

    @classmethod
    def from_env(cls):
        url = os.getenv("AGENTFORGE_OPENAI_BASE_URL", "").rstrip("/")
        if url:
            parts = urlsplit(url)
            if (parts.scheme != "https" or not parts.hostname or parts.username is not None
                    or parts.port not in (None, 443) or parts.query or parts.fragment
                    or "\\" in url or any(ord(character) <= 32 for character in url)):
                raise ValueError("OpenAI-compatible base URL must be a public HTTPS URL on port 443")
        return cls(models_from_env("AGENTFORGE_OLLAMA_MODELS"),
                   models_from_env("AGENTFORGE_OPENAI_MODELS"), url)

    def configured(self, name):
        if name == "offline":
            return ("rules-v1",)
        if name == "ollama":
            return self.ollama_models
        if name == "openai" and self.openai_url and os.getenv("AGENTFORGE_SECRET_OPENAI"):
            return self.openai_models
        return ()


@dataclass(frozen=True)
class Completion:
    text: str
    usage: dict


class Provider(Protocol):
    def completion(self, model: str, messages: list[dict], timeout: float) -> Completion: ...
    def models(self, timeout: float) -> set[str]: ...


def usage(data, names):
    return {label: data[field] for label, field in names.items()
            if type(data.get(field)) is int and 0 <= data[field] <= 10_000_000}


class OpenAI:
    def __init__(self, url, key):
        self.url = url
        self.key = key

    def request(self, path, timeout, body=None):
        hostname = urlsplit(self.url).hostname
        return request_json(self.url + path, frozenset({hostname}), body=body,
                            authorization="Bearer " + self.key, timeout=timeout, redirects=False)

    def completion(self, model, messages, timeout):
        response = self.request("/chat/completions", timeout, {
            "model": model, "messages": messages, "stream": False, "max_tokens": 2048,
        })
        return Completion(response["choices"][0]["message"]["content"],
                          usage(response.get("usage") or {}, {"input_count": "prompt_tokens",
                                "output_count": "completion_tokens", "total_count": "total_tokens"}))

    def models(self, timeout):
        return {item["id"] for item in self.request("/models", timeout)["data"]}


class Ollama:
    @staticmethod
    def request(path, timeout, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=timeout)
        try:
            method = "GET" if body is None else "POST"
            connection.request(method, path, body=json.dumps(body, allow_nan=False) if body is not None else None,
                               headers={"Accept": "application/json", "Content-Type": "application/json",
                                        "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError(f"Ollama returned HTTP {response.status}")
            data = response.read(MAX_BODY + 1)
            if len(data) > MAX_BODY:
                raise ValueError("Ollama response exceeds its size limit")
            return json.loads(data)
        finally:
            connection.close()

    def completion(self, model, messages, timeout):
        response = self.request("/api/chat", timeout, {
            "model": model, "messages": messages, "stream": False, "format": "json",
            "options": {"num_predict": 2048},
        })
        return Completion(response["message"]["content"],
                          usage(response, {"input_count": "prompt_eval_count", "output_count": "eval_count"}))

    def models(self, timeout):
        return {item["name"] for item in self.request("/api/tags", timeout)["models"]}


def adapter(settings, name) -> Provider:
    if not settings.configured(name):
        raise ValueError("The selected AI provider is not configured")
    if name == "ollama":
        return Ollama()
    if name == "openai":
        return OpenAI(settings.openai_url, os.environ["AGENTFORGE_SECRET_OPENAI"])
    raise ValueError("The deterministic provider runs inside AgentForge")


def prompt_text(value):
    secrets = tuple(item for name, item in os.environ.items()
                    if name.startswith("AGENTFORGE_SECRET_") and item)
    return redact(value, secrets)


async def model_list(settings, name):
    configured = settings.configured(name)
    if name == "offline" or not configured:
        return {"provider": name, "configured": bool(configured), "available": name == "offline",
                "models": list(configured)}
    try:
        async with asyncio.timeout(3):
            names = await asyncio.to_thread(adapter(settings, name).models, 2.5)
    except (TimeoutError, OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError):
        return {"provider": name, "configured": True, "available": False, "models": []}
    return {"provider": name, "configured": True, "available": True,
            "models": [model for model in configured if model in names]}
