import json
from pathlib import Path

from bot_assessor.command import CommandResult
from bot_assessor.config import AssessorConfig, BotConfig, RuntimeOptions
from bot_assessor.orchestrator import BotAssessor
from bot_assessor.publishers import PublicationResult


class FakeRunner:
    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def run(self, command, *, cwd=None, env=None, timeout_seconds=900):
        if command[:2] == ["git", "branch"]:
            return CommandResult(list(command), str(cwd), 0, "main\n", "")
        if command[:2] == ["git", "rev-parse"] and "--short" in command:
            return CommandResult(list(command), str(cwd), 0, "abc123\n", "")
        if command[:2] == ["git", "rev-parse"]:
            return CommandResult(list(command), str(cwd), 0, "abc123def\n", "")
        if command[:2] == ["git", "log"]:
            return CommandResult(list(command), str(cwd), 0, "Test commit\n", "")
        if command[:2] == ["git", "status"]:
            return CommandResult(list(command), str(cwd), 0, "", "")
        if command[:3] == ["railway", "deployment", "list"]:
            return CommandResult(list(command), str(cwd), 0, '[{"id":"dep_1","status":"SUCCESS","meta":{"commitHash":"def456789","branch":"main"}}]', "")
        if command[:2] == ["railway", "logs"]:
            return CommandResult(list(command), str(cwd), 0, "INFO trade_opened\n", "")
        return CommandResult(list(command), str(cwd), 0, '{"summary":{"total_trades":1,"total_pnl":3.5,"profit_factor":2.0}}', "")


class StubGithub:
    def publish(self, **kwargs):
        return PublicationResult(ok=True, url="https://github.test/report")


class StubTelegram:
    def notify_daily_digest(self, *args, **kwargs):
        return PublicationResult(ok=True)


class StubRedis:
    def publish_json(self, key, payload, *, enabled):
        return PublicationResult(ok=True, skipped=not enabled)


def test_orchestrator_dry_run_writes_artifacts(tmp_path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    config = AssessorConfig(
        github_repo="owner/bot-assessor",
        artifact_dir=str(tmp_path / "artifacts"),
        workdir=str(tmp_path / "workdir"),
        bots=[BotConfig(id="bot", name="Bot", github_repo="owner/bot", repo_path=str(repo), railway_service="svc", backtest_command=["python", "bt.py"])],
    )

    result = BotAssessor(config, RuntimeOptions(dry_run=True), runner=FakeRunner(repo), github=StubGithub(), telegram=StubTelegram(), redis_publisher=StubRedis()).run()

    assert len(result.reviews) == 1
    assert Path(result.artifacts["markdown"]).exists()
    payload = json.loads(Path(result.artifacts["json"]).read_text(encoding="utf-8"))
    assert payload["reviews"][0]["backtest"]["total_pnl"] == 3.5
    assert payload["reviews"][0]["production"]["railway"]["status"] == "SUCCESS"
    assert payload["reviews"][0]["production"]["active_short_commit"] == "def4567"
    assert payload["reviews"][0]["portfolio"]["decision"]
    assert payload["reviews"][0]["postmortem"]["headline"]