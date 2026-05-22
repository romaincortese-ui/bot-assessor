from pathlib import Path

from bot_assessor.command import CommandResult
from bot_assessor.config import AssessorConfig, BotConfig, RuntimeOptions
from bot_assessor.optimizer import WeeklyOptimizer, evaluate_guardrails
from bot_assessor.publishers import PublicationResult


class OptimizerRunner:
    def __init__(self, *, changed_file: str = "config/calibration.json", candidate_output: str | None = None) -> None:
        self.changed_file = changed_file
        self.candidate_output = candidate_output or "trades=12 pnl=14.00 pf=1.80 max_dd=-3.00%"
        self.commands: list[list[str]] = []
        self.backtest_calls = 0
        self.status_calls = 0

    def run(self, command, *, cwd=None, env=None, timeout_seconds=900):
        command = list(command)
        self.commands.append(command)
        if command[:2] == ["git", "status"]:
            self.status_calls += 1
            if self.status_calls == 1:
                return CommandResult(command, str(cwd), 0, "", "")
            return CommandResult(command, str(cwd), 0, f" M {self.changed_file}\n", "")
        if command[:2] == ["git", "commit"]:
            return CommandResult(command, str(cwd), 0, "committed", "")
        if command[:2] == ["git", "push"]:
            return CommandResult(command, str(cwd), 0, "pushed", "")
        if command[:1] == ["git"]:
            return CommandResult(command, str(cwd), 0, "ok", "")
        if command == ["python", "bt.py"]:
            self.backtest_calls += 1
            output = "trades=12 pnl=10.00 pf=1.50 max_dd=-3.00%" if self.backtest_calls == 1 else self.candidate_output
            return CommandResult(command, str(cwd), 0, output, "")
        if command == ["python", "optimize.py"]:
            return CommandResult(command, str(cwd), 0, "optimized", "")
        if command == ["pytest"]:
            return CommandResult(command, str(cwd), 0, "passed", "")
        return CommandResult(command, str(cwd), 0, "ok", "")


class StubPRs:
    def __init__(self) -> None:
        self.created = []
        self.merged = []

    def create_pr(self, **kwargs):
        self.created.append(kwargs)
        return PublicationResult(ok=True, url="https://github.test/pr/1", metadata={"number": 1})

    def merge_pr(self, **kwargs):
        self.merged.append(kwargs)
        return PublicationResult(ok=True, url="https://github.test/pr/1")


class StubSummary:
    def publish(self, **kwargs):
        return PublicationResult(ok=True, url="https://github.test/issues/1")


def _config(tmp_path: Path, bot: BotConfig) -> AssessorConfig:
    return AssessorConfig(github_repo="owner/bot-assessor", artifact_dir=str(tmp_path / "artifacts"), workdir=str(tmp_path / "workdir"), bots=[bot])


def _bot(repo: Path, **overrides) -> BotConfig:
    values = dict(
        id="mexc_spot",
        name="MEXC Spot Bot",
        github_repo="owner/spot",
        repo_path=str(repo),
        test_command=["pytest"],
        backtest_command=["python", "bt.py"],
        optimizer_enabled=True,
        optimizer_command=["python", "optimize.py"],
        optimizer_backtests=[{"name": "30d", "command": ["python", "bt.py"], "env": {}}],
        optimizer_guardrails={"require_tests": True, "require_backtests": True, "require_pnl_improvement": True, "require_profit_factor_not_worse": True, "min_trades": 5, "max_drawdown_worsening": 0.02},
        allowed_pr_file_patterns=["config/*.json"],
        auto_merge_enabled=False,
        auto_merge_allowed_file_patterns=["**/*calibration*.json"],
    )
    values.update(overrides)
    return BotConfig(**values)


def test_weekly_optimizer_opens_pr_after_checks_pass(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    runner = OptimizerRunner()
    prs = StubPRs()

    result = WeeklyOptimizer(_config(tmp_path, _bot(repo)), RuntimeOptions(), runner=runner, pr_publisher=prs, summary_publisher=StubSummary()).run()

    assert result.results[0].status == "pr_opened"
    assert prs.created[0]["repo"] == "owner/spot"
    assert prs.merged == []
    assert Path(result.artifacts["json"]).exists()


def test_weekly_optimizer_auto_merges_only_when_allowed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    prs = StubPRs()
    bot = _bot(repo, auto_merge_enabled=True)

    result = WeeklyOptimizer(_config(tmp_path, bot), RuntimeOptions(allow_auto_merge=True), runner=OptimizerRunner(), pr_publisher=prs, summary_publisher=StubSummary()).run()

    assert result.results[0].status == "auto_merged"
    assert prs.merged[0]["repo"] == "owner/spot"


def test_weekly_optimizer_rejects_auto_merge_file_outside_allowlist(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    prs = StubPRs()
    bot = _bot(repo, auto_merge_enabled=True)

    result = WeeklyOptimizer(
        _config(tmp_path, bot),
        RuntimeOptions(allow_auto_merge=True),
        runner=OptimizerRunner(changed_file="config/strategy.json"),
        pr_publisher=prs,
        summary_publisher=StubSummary(),
    ).run()

    assert result.results[0].status == "pr_opened"
    assert prs.merged == []


def test_weekly_optimizer_skips_missing_optimizer_command(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    bot = _bot(repo, optimizer_command=[])

    result = WeeklyOptimizer(_config(tmp_path, bot), RuntimeOptions(), runner=OptimizerRunner(), pr_publisher=StubPRs(), summary_publisher=StubSummary()).run()

    assert result.results[0].status == "skipped"
    assert "optimizer_command" in (result.results[0].optimizer.error or "")


def test_weekly_optimizer_runs_internal_candidate_generator(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "mexcbot").mkdir()
    (repo / "backtest").mkdir()
    (repo / "mexcbot" / "config.py").write_text(
        'score_threshold=env_float("SCORE_THRESHOLD", 37.0)\n'
        'scalper_threshold=env_float("SCALPER_THRESHOLD", env_float("SCORE_THRESHOLD", 42.0))\n',
        encoding="utf-8",
    )
    (repo / "backtest" / "config.py").write_text(
        'score_threshold=env_float("BACKTEST_SCORE_THRESHOLD", env_float("SCORE_THRESHOLD", 37.0))\n'
        'scalper_threshold=env_float("BACKTEST_SCALPER_THRESHOLD", env_float("SCALPER_THRESHOLD", env_float("SCORE_THRESHOLD", 42.0)))\n',
        encoding="utf-8",
    )
    bot = _bot(repo, optimizer_command=[], candidate_generator="mexc_spot_thresholds")

    result = WeeklyOptimizer(_config(tmp_path, bot), RuntimeOptions(), runner=OptimizerRunner(), pr_publisher=StubPRs(), summary_publisher=StubSummary()).run()

    assert result.results[0].optimizer.ok
    assert "generate-candidate" in result.results[0].optimizer.command
    assert (repo / "bot_assessor_candidate_config.json").exists()


def test_guardrails_fail_when_candidate_does_not_improve(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    result = WeeklyOptimizer(
        _config(tmp_path, _bot(repo)),
        RuntimeOptions(),
        runner=OptimizerRunner(candidate_output="trades=12 pnl=8.00 pf=1.40 max_dd=-3.00%"),
        pr_publisher=StubPRs(),
        summary_publisher=StubSummary(),
    ).run()

    assert result.results[0].status == "failed"
    assert any("did not beat baseline" in reason for reason in result.results[0].guardrails.reasons)


def test_weekly_optimizer_requires_pr_file_allowlist(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    bot = _bot(repo, allowed_pr_file_patterns=[])

    result = WeeklyOptimizer(_config(tmp_path, bot), RuntimeOptions(), runner=OptimizerRunner(), pr_publisher=StubPRs(), summary_publisher=StubSummary()).run()

    assert result.results[0].status == "failed"
    assert any("allowed_pr_file_patterns" in reason for reason in result.results[0].errors)


def test_guardrails_can_require_return_and_trade_count_quality(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    bot = _bot(
        repo,
        optimizer_guardrails={
            "require_tests": True,
            "require_backtests": True,
            "require_pnl_improvement": True,
            "require_profit_factor_not_worse": True,
            "require_return_pct_not_worse": True,
            "max_trade_count_drop_pct": 0.10,
            "min_trades": 5,
        },
    )
    runner = OptimizerRunner(candidate_output="trades=5 pnl=14.00 return=0.50% pf=1.80 max_dd=-3.00%")

    result = WeeklyOptimizer(_config(tmp_path, bot), RuntimeOptions(), runner=runner, pr_publisher=StubPRs(), summary_publisher=StubSummary()).run()

    assert result.results[0].status == "failed"
    assert any("trade count dropped" in reason for reason in result.results[0].guardrails.reasons)