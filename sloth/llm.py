"""Tiny client for Unsloth's OpenAI-compatible local server (/v1/chat/completions)."""
from __future__ import annotations

import requests

from .config import Config


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._model = cfg.model or None

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.cfg.api_key}", "Content-Type": "application/json"}

    def models(self) -> list[str]:
        try:
            r = requests.get(f"{self.cfg.base_url}/models", headers=self._headers(), timeout=10)
            r.raise_for_status()
            return [m["id"] for m in r.json().get("data", [])]
        except Exception as e:
            raise LLMError(f"Cannot reach the model server at {self.cfg.base_url}: {e}") from e

    @property
    def model(self) -> str:
        if not self._model:
            ids = self.models()
            if not ids:
                raise LLMError("The server reports no loaded model. Load one in Unsloth first.")
            self._model = ids[0]
        return self._model

    def chat(self, prompt: str, image_b64: str | None = None, max_tokens: int = 160) -> str:
        content: list | str
        if image_b64:
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ]
        else:
            content = prompt
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            r = requests.post(
                f"{self.cfg.base_url}/chat/completions",
                json=body, headers=self._headers(), timeout=self.cfg.request_timeout,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"] or ""
        except requests.RequestException as e:
            raise LLMError(f"Model request failed: {e}") from e
        except (KeyError, IndexError, ValueError) as e:
            raise LLMError(f"Unexpected response from model server: {e}") from e
