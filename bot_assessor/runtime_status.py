from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bot_assessor.config import BotConfig


MAX_STATUS_TEXT = 12000


@dataclass(frozen=True)
class RuntimeStatusSnapshot:
    ok: bool
    sources: list[str] = field(default_factory=list)
    text: str = ""
    payloads: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "sources": self.sources,
            "payloads": self.payloads,
            "errors": self.errors,
            "text_excerpt": self.text[:2000],
        }


class RuntimeStatusCollector:
    def __init__(self, *, redis_url: str | None = None) -> None:
        self.redis_url = redis_url if redis_url is not None else os.getenv("REDIS_URL", "").strip()

    def collect(self, bot: BotConfig, *, repo_path: str | Path) -> RuntimeStatusSnapshot:
        sources: list[str] = []
        chunks: list[str] = []
        payloads: dict[str, Any] = {}
        errors: list[str] = []

        for raw_path in [*bot.runtime_status_files, *bot.daily_review_files]:
            path = Path(raw_path)
            if not path.is_absolute():
                path = Path(repo_path) / path
            if not path.exists():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[-MAX_STATUS_TEXT:]
            except OSError as exc:
                errors.append(f"{raw_path}: {exc}")
                continue
            source = f"file:{raw_path}"
            sources.append(source)
            chunks.append(f"[RUNTIME_STATUS source={source}]\n{text}")
            payloads[source] = _json_or_text(text)

        redis_keys = list(dict.fromkeys([*bot.runtime_status_redis_keys, *(key for key in [bot.compatible_review_redis_key] if key)]))
        if redis_keys and self.redis_url:
            try:
                import redis

                client = redis.from_url(self.redis_url, socket_connect_timeout=10, socket_timeout=10)
                for key in redis_keys:
                    raw = client.get(key)
                    if raw is None:
                        continue
                    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                    source = f"redis:{key}"
                    sources.append(source)
                    chunks.append(f"[RUNTIME_STATUS source={source}]\n{text[-MAX_STATUS_TEXT:]}")
                    payloads[source] = _json_or_text(text)
            except Exception as exc:  # pragma: no cover - exact redis exceptions vary by version
                errors.append(f"redis: {exc}")
        elif redis_keys and not self.redis_url:
            errors.append("redis: REDIS_URL is not configured")

        text = "\n".join(chunks)
        return RuntimeStatusSnapshot(ok=bool(sources), sources=sources, text=text, payloads=payloads, errors=errors)


def _json_or_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text_excerpt": text[:2000]}