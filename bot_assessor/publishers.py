from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import requests

from bot_assessor.portfolio import fleet_rollup


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

    def notify_daily_digest(self, reviews: list[dict[str, Any]], *, report_url: str | None, dry_run: bool = False) -> PublicationResult:
        return self.send_message(build_daily_digest_message(reviews, report_url=report_url), dry_run=dry_run)

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


def build_daily_digest_message(reviews: list[dict[str, Any]], *, report_url: str | None = None) -> str:
    rollup = fleet_rollup(reviews)
    lines = ["Daily Bot Assessment"]
    for currency, values in (rollup.get("by_currency") or {}).items():
        lines.append(
            f"{currency}: live P&L {_format_money(values.get('live_pnl_amount'), currency)} | "
            f"risk@stop {_format_money(values.get('risk_at_stop'), currency)} | margin {_format_money(values.get('margin_used'), currency)}"
        )
    attention = rollup.get("attention") or []
    if attention:
        lines.append("Needs attention: " + ", ".join(attention[:5]))
    best = rollup.get("best_backtest")
    worst = rollup.get("worst_backtest")
    if best:
        lines.append(f"Best 30d: {best.get('bot')} ({_format_number(best.get('pnl'))})")
    if worst:
        lines.append(f"Weakest 30d: {worst.get('bot')} ({_format_number(worst.get('pnl'))})")
    high_findings = []
    for review in reviews:
        postmortem = review.get("postmortem") or {}
        if postmortem.get("severity") == "high":
            high_findings.append(str(review.get("bot_name") or review.get("bot_id")))
    if high_findings:
        lines.append("High-severity post-mortems: " + ", ".join(high_findings[:5]))
    if report_url:
        lines.append(f"Report: {report_url}")
    return "\n".join(lines)


def _format_money(value: Any, currency: str) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "n/a"
    symbol = "$" if currency == "USD" else "£" if currency == "GBP" else f"{currency} "
    sign = "+" if amount >= 0 else "-"
    return f"{sign}{symbol}{abs(amount):.2f}"


def _format_number(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "n/a"


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