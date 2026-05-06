from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bot_assessor.command import CommandRunner
from bot_assessor.config import BotConfig


@dataclass(frozen=True)
class LogCollection:
    source: str
    ok: bool
    text: str
    error: str | None = None


class RailwayLogCollector:
    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def collect(self, bot: BotConfig, *, repo_path: str | Path, lines: int) -> LogCollection:
        if not bot.railway_service:
            return LogCollection("railway", False, "", "No railway_service configured")
        command = [
            "railway",
            "logs",
            "--service",
            bot.railway_service,
            "--environment",
            bot.railway_environment,
            "--lines",
            str(lines),
        ]
        result = self.runner.run(command, cwd=repo_path, timeout_seconds=180)
        if not result.ok:
            return LogCollection("railway", False, result.combined_output, result.stderr.strip() or result.stdout.strip())
        return LogCollection("railway", True, result.stdout)