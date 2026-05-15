from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bot_assessor.command import CommandRunner
from bot_assessor.config import BotConfig


MAX_LOG_LINES_PER_REQUEST = 500


@dataclass(frozen=True)
class LogCollection:
    source: str
    ok: bool
    text: str
    error: str | None = None
    attempted_commands: list[list[str]] | None = None


@dataclass(frozen=True)
class RailwayDeploymentStatus:
    ok: bool
    service: str | None
    environment: str | None
    project_id: str | None = None
    deployment_id: str | None = None
    status: str | None = None
    commit: str | None = None
    short_commit: str | None = None
    branch: str | None = None
    created_at: str | None = None
    source: str = "railway"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "source": self.source,
            "service": self.service,
            "environment": self.environment,
            "project_id": self.project_id,
            "deployment_id": self.deployment_id,
            "status": self.status,
            "commit": self.commit,
            "short_commit": self.short_commit,
            "branch": self.branch,
            "created_at": self.created_at,
            "error": self.error,
        }


class RailwayLogCollector:
    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def collect(self, bot: BotConfig, *, repo_path: str | Path, lines: int, window_hours: int = 24) -> LogCollection:
        if not bot.railway_service:
            return LogCollection("railway", False, "", "No railway_service configured")
        if lines > MAX_LOG_LINES_PER_REQUEST and window_hours > 0:
            chunked = self._collect_chunked(bot, repo_path=repo_path, lines=lines, window_hours=window_hours)
            if chunked.ok:
                return chunked
        return self._collect_once(bot, repo_path=repo_path, lines=lines)

    def _collect_once(self, bot: BotConfig, *, repo_path: str | Path, lines: int) -> LogCollection:
        command = [
            "railway",
            "logs",
            *service_flags(bot),
            "--lines",
            str(lines),
        ]
        result = self.runner.run(command, cwd=repo_path, timeout_seconds=180)
        if not result.ok:
            return LogCollection("railway", False, result.combined_output, result.stderr.strip() or result.stdout.strip(), [command])
        return LogCollection("railway", True, result.stdout, attempted_commands=[command])

    def _collect_chunked(self, bot: BotConfig, *, repo_path: str | Path, lines: int, window_hours: int) -> LogCollection:
        chunk_count = max(2, min(12, (lines + MAX_LOG_LINES_PER_REQUEST - 1) // MAX_LOG_LINES_PER_REQUEST))
        chunk_hours = max(1, (window_hours + chunk_count - 1) // chunk_count)
        end = datetime.now(timezone.utc)
        chunks: list[str] = []
        errors: list[str] = []
        commands: list[list[str]] = []
        for index in range(chunk_count, 0, -1):
            until = end - timedelta(hours=chunk_hours * (index - 1))
            since = max(end - timedelta(hours=window_hours), until - timedelta(hours=chunk_hours))
            command = [
                "railway",
                "logs",
                *service_flags(bot),
                "--since",
                _stamp(since),
                "--until",
                _stamp(until),
                "--lines",
                str(MAX_LOG_LINES_PER_REQUEST),
            ]
            commands.append(command)
            result = self.runner.run(command, cwd=repo_path, timeout_seconds=180)
            if result.ok and result.stdout.strip():
                chunks.append(result.stdout.strip())
            elif not result.ok:
                errors.append(result.stderr.strip() or result.stdout.strip() or "unknown Railway log error")
        text = "\n".join(_dedupe_lines("\n".join(chunks).splitlines()))
        if text:
            return LogCollection("railway_chunked", True, text, "; ".join(errors) if errors else None, commands)
        return LogCollection("railway_chunked", False, "\n".join(errors), "; ".join(errors) if errors else "No log lines returned", commands)


class RailwayDeploymentCollector:
    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def collect(self, bot: BotConfig, *, repo_path: str | Path) -> RailwayDeploymentStatus:
        if not bot.railway_service:
            return RailwayDeploymentStatus(False, None, bot.railway_environment, bot.railway_project_id, error="No railway_service configured")
        command = ["railway", "deployment", "list", *service_flags(bot), "--limit", "1", "--json"]
        result = self.runner.run(command, cwd=repo_path, timeout_seconds=120)
        if result.ok:
            parsed = parse_deployment_status(result.stdout, bot)
            if parsed.ok:
                return parsed
        fallback = ["railway", "service", "status", *service_flags(bot), "--json"]
        fallback_result = self.runner.run(fallback, cwd=repo_path, timeout_seconds=120)
        if fallback_result.ok:
            parsed = parse_service_status(fallback_result.stdout, bot)
            if parsed.ok:
                return parsed
        error = result.stderr.strip() or result.stdout.strip() or fallback_result.stderr.strip() or fallback_result.stdout.strip()
        return RailwayDeploymentStatus(
            False,
            bot.railway_service,
            bot.railway_environment,
            bot.railway_project_id,
            source="railway",
            error=error or "Railway deployment status unavailable",
        )


def service_flags(bot: BotConfig) -> list[str]:
    flags: list[str] = []
    if bot.railway_project_id:
        flags.extend(["--project", bot.railway_project_id])
    if bot.railway_service:
        flags.extend(["--service", bot.railway_service])
    if bot.railway_environment_id:
        flags.extend(["--environment", bot.railway_environment_id])
    elif bot.railway_environment:
        flags.extend(["--environment", bot.railway_environment])
    return flags


def parse_deployment_status(text: str, bot: BotConfig) -> RailwayDeploymentStatus:
    try:
        payload = json.loads(text or "null")
    except json.JSONDecodeError as exc:
        return RailwayDeploymentStatus(False, bot.railway_service, bot.railway_environment, bot.railway_project_id, error=f"Invalid Railway deployment JSON: {exc}")
    item = _first_payload_item(payload)
    if item is None:
        return RailwayDeploymentStatus(True, bot.railway_service, bot.railway_environment, bot.railway_project_id, status="not_found")
    metadata = _dict_value(item, "meta") or _dict_value(item, "metadata") or {}
    commit = _first_text(item, metadata, "commitHash", "commit_sha", "commitSha", "commit", "sourceCommit")
    return RailwayDeploymentStatus(
        True,
        bot.railway_service,
        bot.railway_environment,
        bot.railway_project_id,
        deployment_id=_first_text(item, metadata, "id", "deploymentId"),
        status=_first_text(item, metadata, "status", "state", "deploymentStatus"),
        commit=commit,
        short_commit=commit[:7] if commit else None,
        branch=_first_text(item, metadata, "branch", "branchName", "sourceBranch"),
        created_at=_first_text(item, metadata, "createdAt", "created_at", "created", "updatedAt"),
    )


def parse_service_status(text: str, bot: BotConfig) -> RailwayDeploymentStatus:
    try:
        payload = json.loads(text or "null")
    except json.JSONDecodeError as exc:
        return RailwayDeploymentStatus(False, bot.railway_service, bot.railway_environment, bot.railway_project_id, error=f"Invalid Railway service JSON: {exc}")
    item = payload if isinstance(payload, dict) else _first_payload_item(payload)
    if not isinstance(item, dict):
        return RailwayDeploymentStatus(False, bot.railway_service, bot.railway_environment, bot.railway_project_id, error="Railway service status JSON did not contain an object")
    return RailwayDeploymentStatus(
        True,
        bot.railway_service,
        bot.railway_environment,
        bot.railway_project_id,
        status=_first_text(item, {}, "status", "state"),
        source="railway_service_status",
    )


def _first_payload_item(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, list):
        return payload[0] if payload and isinstance(payload[0], dict) else None
    if not isinstance(payload, dict):
        return None
    for key in ("deployments", "data", "items", "edges"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict) and isinstance(first.get("node"), dict):
                return first["node"]
            if isinstance(first, dict):
                return first
    return payload


def _dict_value(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = payload.get(key)
    return value if isinstance(value, dict) else None


def _first_text(primary: dict[str, Any], secondary: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        for payload in (primary, secondary):
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return None


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dedupe_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
    return result