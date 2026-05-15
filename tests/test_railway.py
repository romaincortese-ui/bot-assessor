import json
from pathlib import Path

from bot_assessor.command import CommandResult
from bot_assessor.config import BotConfig
from bot_assessor.railway import RailwayDeploymentCollector, RailwayLogCollector, parse_deployment_status


class RailwayRunner:
    def __init__(self, *, fail_chunks: bool = False) -> None:
        self.fail_chunks = fail_chunks
        self.commands: list[list[str]] = []

    def run(self, command, *, cwd=None, env=None, timeout_seconds=900):
        command = list(command)
        self.commands.append(command)
        if command[:3] == ["railway", "deployment", "list"]:
            payload = [{"id": "dep_1", "status": "SUCCESS", "createdAt": "2026-05-15T10:00:00Z", "meta": {"commitHash": "abcdef123456", "branch": "main"}}]
            return CommandResult(command, str(cwd), 0, json.dumps(payload), "")
        if command[:2] == ["railway", "logs"] and "--since" in command:
            if self.fail_chunks:
                return CommandResult(command, str(cwd), 1, "", "chunk failed")
            return CommandResult(command, str(cwd), 0, f"INFO chunk since={command[command.index('--since') + 1]}\n", "")
        if command[:2] == ["railway", "logs"]:
            return CommandResult(command, str(cwd), 0, "INFO fallback\n", "")
        return CommandResult(command, str(cwd), 0, "{}", "")


def test_chunked_log_collection_for_large_windows(tmp_path: Path) -> None:
    bot = BotConfig(id="indices", name="Indices", github_repo="owner/indices", railway_service="indices-bot")
    runner = RailwayRunner()

    result = RailwayLogCollector(runner).collect(bot, repo_path=tmp_path, lines=1200, window_hours=24)

    assert result.ok is True
    assert result.source == "railway_chunked"
    assert len(result.attempted_commands or []) == 3
    assert all("--since" in command for command in result.attempted_commands or [])


def test_log_collection_falls_back_to_one_shot_when_chunks_fail(tmp_path: Path) -> None:
    bot = BotConfig(id="indices", name="Indices", github_repo="owner/indices", railway_service="indices-bot")
    runner = RailwayRunner(fail_chunks=True)

    result = RailwayLogCollector(runner).collect(bot, repo_path=tmp_path, lines=1200, window_hours=24)

    assert result.ok is True
    assert result.source == "railway"
    assert "INFO fallback" in result.text


def test_deployment_status_parses_commit_metadata() -> None:
    bot = BotConfig(id="gold", name="Gold", github_repo="owner/gold", railway_service="worker")
    payload = [{"id": "dep_1", "status": "SUCCESS", "meta": {"commitHash": "abcdef123456", "branch": "main"}}]

    status = parse_deployment_status(json.dumps(payload), bot)

    assert status.ok is True
    assert status.deployment_id == "dep_1"
    assert status.status == "SUCCESS"
    assert status.short_commit == "abcdef1"


def test_deployment_collector_runs_railway_cli(tmp_path: Path) -> None:
    bot = BotConfig(id="gold", name="Gold", github_repo="owner/gold", railway_service="worker")
    runner = RailwayRunner()

    status = RailwayDeploymentCollector(runner).collect(bot, repo_path=tmp_path)

    assert status.ok is True
    assert status.status == "SUCCESS"
    assert runner.commands[0][:3] == ["railway", "deployment", "list"]