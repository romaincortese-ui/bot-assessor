from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import requests


@dataclass(frozen=True)
class PublicationResult:
    ok: bool
    url: str | None = None
    skipped: bool = False
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class GitHubIssuePublisher:
    def __init__(self, *, repo: str, token: str | None = None, session: requests.Session | None = None) -> None:
        self.repo = repo
        self.token = token or os.getenv("BOT_ASSESSOR_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")
        self.session = session or requests.Session()

    def publish(self, *, title: str, body: str, labels: list[str], dry_run: bool = False) -> PublicationResult:
        if dry_run or not self.token:
            return PublicationResult(ok=True, skipped=True)
        response = self.session.post(
            f"https://api.github.com/repos/{self.repo}/issues",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"},
            json={"title": title, "body": body, "labels": labels},
            timeout=30,
        )
        if response.status_code >= 300:
            return PublicationResult(ok=False, error=f"GitHub issue publish failed: {response.status_code} {response.text[:500]}")
        payload = response.json()
        return PublicationResult(ok=True, url=payload.get("html_url"), metadata={"number": payload.get("number")})


class GitHubPullRequestPublisher:
    def __init__(self, *, token: str | None = None, session: requests.Session | None = None) -> None:
        self.token = token or os.getenv("BOT_ASSESSOR_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")
        self.session = session or requests.Session()

    def create_pr(
        self,
        *,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str,
        labels: list[str] | None = None,
        dry_run: bool = False,
    ) -> PublicationResult:
        if dry_run or not self.token:
            return PublicationResult(ok=True, skipped=True)
        response = self.session.post(
            f"https://api.github.com/repos/{repo}/pulls",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"},
            json={"title": title, "body": body, "head": head, "base": base, "draft": False},
            timeout=30,
        )
        if response.status_code >= 300:
            return PublicationResult(ok=False, error=f"GitHub PR creation failed for {repo}: {response.status_code} {response.text[:500]}")
        payload = response.json()
        number = payload.get("number")
        if labels and number:
            self.session.post(
                f"https://api.github.com/repos/{repo}/issues/{number}/labels",
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"},
                json={"labels": labels},
                timeout=30,
            )
        return PublicationResult(ok=True, url=payload.get("html_url"), metadata={"number": number})

    def merge_pr(self, *, repo: str, number: int | None, commit_title: str, dry_run: bool = False) -> PublicationResult:
        if dry_run or not self.token or number is None:
            return PublicationResult(ok=True, skipped=True)
        response = self.session.put(
            f"https://api.github.com/repos/{repo}/pulls/{number}/merge",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"},
            json={"commit_title": commit_title, "merge_method": "squash"},
            timeout=30,
        )
        if response.status_code >= 300:
            return PublicationResult(ok=False, error=f"GitHub PR merge failed for {repo}#{number}: {response.status_code} {response.text[:500]}")
        payload = response.json()
        return PublicationResult(ok=True, url=payload.get("html_url"), metadata={"merged": payload.get("merged")})


class TelegramNotifier:
    def __init__(self, *, token: str | None = None, chat_id: str | None = None, session: requests.Session | None = None) -> None:
        self.token = token or os.getenv("BOT_ASSESSOR_TELEGRAM_TOKEN", "").strip()
        self.chat_id = chat_id or os.getenv("BOT_ASSESSOR_TELEGRAM_CHAT_ID", "").strip()
        self.session = session or requests.Session()

    def notify_report_ready(self, *, report_url: str | None, dry_run: bool = False) -> PublicationResult:
        text = "New daily report ready"
        if report_url:
            text = f"{text}: {report_url}"
        return self.send_message(text, dry_run=dry_run)

    def send_message(self, text: str, *, dry_run: bool = False) -> PublicationResult:
        if dry_run or not self.token or not self.chat_id:
            return PublicationResult(ok=True, skipped=True)
        response = self.session.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True},
            timeout=20,
        )
        if response.status_code >= 300:
            return PublicationResult(ok=False, error=f"Telegram send failed: {response.status_code} {response.text[:500]}")
        return PublicationResult(ok=True)


class RedisPublisher:
    def __init__(self, *, redis_url: str | None = None) -> None:
        self.redis_url = redis_url or os.getenv("REDIS_URL", "").strip()

    def publish_json(self, key: str | None, payload: dict[str, Any], *, enabled: bool) -> PublicationResult:
        if not enabled or not key or not self.redis_url:
            return PublicationResult(ok=True, skipped=True)
        try:
            import redis

            client = redis.from_url(self.redis_url, socket_connect_timeout=10, socket_timeout=10)
            client.set(key, json.dumps(payload), ex=7 * 24 * 3600)
            return PublicationResult(ok=True)
        except Exception as exc:  # pragma: no cover - exact redis exceptions vary by version
            return PublicationResult(ok=False, error=str(exc))