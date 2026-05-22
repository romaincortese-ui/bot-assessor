from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from bot_assessor.backtest import BacktestResult, BacktestRunner
from bot_assessor.candidates import generate_candidate
from bot_assessor.command import CommandResult, CommandRunner
from bot_assessor.config import AssessorConfig, BotConfig, RuntimeOptions
from bot_assessor.publishers import GitHubIssuePublisher, GitHubPullRequestPublisher, PublicationResult
from bot_assessor.repository import RepositoryManager


@dataclass(frozen=True)
class OptimizationBacktestScenario:
    name: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandCheck:
    command: list[str]
    ok: bool
    returncode: int | None = None
    output: str = ""
    skipped: bool = False
    error: str | None = None

    @classmethod
    def skipped_check(cls, reason: str) -> "CommandCheck":
        return cls(command=[], ok=True, skipped=True, error=reason)

    @classmethod
    def from_result(cls, result: CommandResult) -> "CommandCheck":
        return cls(
            command=result.command,
            ok=result.ok,
            returncode=result.returncode,
            output=result.combined_output[-12000:],
            error=None if result.ok else (result.stderr.strip() or result.stdout.strip())[-2000:],
        )


@dataclass(frozen=True)
class GuardrailDecision:
    passed: bool
    reasons: list[str]


@dataclass(frozen=True)
class BotOptimizationResult:
    bot_id: str
    bot_name: str
    status: str
    base_branch: str
    branch: str | None
    changed_files: list[str]
    optimizer: CommandCheck
    tests: CommandCheck
    guardrails: GuardrailDecision
    baseline_backtests: dict[str, BacktestResult]
    candidate_backtests: dict[str, BacktestResult]
    pull_request: PublicationResult
    merge: PublicationResult
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WeeklyOptimizationRunResult:
    results: list[BotOptimizationResult]
    report_markdown: str
    artifacts: dict[str, str]
    summary_issue: PublicationResult


class WeeklyOptimizer:
    def __init__(
        self,
        config: AssessorConfig,
        options: RuntimeOptions,
        *,
        runner: CommandRunner | None = None,
        pr_publisher: GitHubPullRequestPublisher | None = None,
        summary_publisher: GitHubIssuePublisher | None = None,
    ) -> None:
        self.config = config
        self.options = options
        self.runner = runner or CommandRunner()
        self.repositories = RepositoryManager(self.runner, workdir=config.workdir)
        self.backtests = BacktestRunner(self.runner)
        self.prs = pr_publisher or GitHubPullRequestPublisher()
        self.summary = summary_publisher or GitHubIssuePublisher(repo=config.github_repo)

    def run(self, *, bot_ids: set[str] | None = None) -> WeeklyOptimizationRunResult:
        generated_at = datetime.now(timezone.utc)
        results: list[BotOptimizationResult] = []
        for bot in self.config.bots:
            if bot_ids and bot.id not in bot_ids:
                continue
            results.append(self._run_bot(bot, generated_at=generated_at))
        markdown = render_optimization_markdown(results, generated_at=generated_at)
        artifacts = write_optimization_artifacts(Path(self.config.artifact_dir), results, markdown, generated_at=generated_at)
        issue = self.summary.publish(
            title=f"Weekly bot optimizer - {generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
            body=markdown,
            labels=["weekly-optimizer", "bot-assessor"],
            dry_run=self.options.dry_run,
        )
        return WeeklyOptimizationRunResult(results=results, report_markdown=markdown, artifacts=artifacts, summary_issue=issue)

    def _run_bot(self, bot: BotConfig, *, generated_at: datetime) -> BotOptimizationResult:
        empty_pr = PublicationResult(ok=True, skipped=True)
        if not bot.optimizer_enabled:
            return self._result(bot, "skipped", None, [], CommandCheck.skipped_check("optimizer disabled"), CommandCheck.skipped_check("not run"), empty_pr, empty_pr)
        if not bot.optimizer_command and not bot.candidate_generator:
            return self._result(
                bot,
                "skipped",
                None,
                [],
            CommandCheck.skipped_check("candidate_generator or optimizer_command is not configured"),
                CommandCheck.skipped_check("not run"),
                empty_pr,
                empty_pr,
            )

        repo_path = self.repositories.ensure_repo(bot)
        branch = self.repositories.create_candidate_branch(bot, repo_path, generated_at=generated_at)
        scenarios = _scenario_configs(bot)
        baseline = self._run_backtest_scenarios(bot, scenarios, repo_path)
        baseline_dirty_files = self.repositories.changed_files(repo_path)
        if baseline_dirty_files:
            error = f"baseline backtests modified the working tree: {', '.join(baseline_dirty_files)}"
            return self._result(bot, "failed", branch, baseline_dirty_files, CommandCheck.skipped_check("not run"), CommandCheck.skipped_check("not run"), empty_pr, empty_pr, baseline, {}, [error])
        optimizer = self._run_candidate_generator(bot, repo_path, branch, baseline, generated_at=generated_at) if bot.candidate_generator else self._run_optimizer_command(bot, repo_path, branch)
        if not optimizer.ok:
            return self._result(bot, "failed", branch, [], optimizer, CommandCheck.skipped_check("optimizer failed"), empty_pr, empty_pr, baseline, {}, [optimizer.error or "optimizer failed"])

        changed_files = self.repositories.changed_files(repo_path)
        if not changed_files:
            return self._result(bot, "skipped", branch, [], optimizer, CommandCheck.skipped_check("optimizer produced no changes"), empty_pr, empty_pr, baseline, {})
        if not bot.allowed_pr_file_patterns:
            error = "allowed_pr_file_patterns is required before bot-assessor can open autonomous optimization PRs"
            return self._result(bot, "failed", branch, changed_files, optimizer, CommandCheck.skipped_check("not run"), empty_pr, empty_pr, baseline, {}, [error])
        disallowed_pr_files = _disallowed_files(changed_files, bot.allowed_pr_file_patterns)
        if disallowed_pr_files:
            error = f"changed files are outside allowed_pr_file_patterns: {', '.join(disallowed_pr_files)}"
            return self._result(bot, "failed", branch, changed_files, optimizer, CommandCheck.skipped_check("not run"), empty_pr, empty_pr, baseline, {}, [error])

        tests = self._run_tests(bot, repo_path)
        candidate = {} if self.options.skip_backtests else self._run_backtest_scenarios(bot, scenarios, repo_path)
        guardrails = evaluate_guardrails(bot, baseline, candidate, tests, skip_backtests=self.options.skip_backtests)
        if not guardrails.passed:
            status = "failed" if _guardrail_execution_failed(tests, baseline, candidate) else "rejected_by_guardrails"
            return self._result(bot, status, branch, changed_files, optimizer, tests, empty_pr, empty_pr, baseline, candidate, guardrails.reasons, guardrails)
        post_check_changed_files = self.repositories.changed_files(repo_path)
        if sorted(post_check_changed_files) != sorted(changed_files):
            error = f"tests or candidate backtests modified the working tree: {', '.join(post_check_changed_files)}"
            return self._result(bot, "failed", branch, post_check_changed_files, optimizer, tests, empty_pr, empty_pr, baseline, candidate, [error], GuardrailDecision(False, [error]))
        if self.options.dry_run:
            return self._result(bot, "passed_dry_run", branch, changed_files, optimizer, tests, empty_pr, empty_pr, baseline, candidate, [], guardrails)

        committed = self.repositories.commit_files(repo_path, changed_files, message=f"Bot assessor weekly optimization for {bot.name}")
        if not committed:
            return self._result(bot, "failed", branch, changed_files, optimizer, tests, empty_pr, empty_pr, baseline, candidate, ["git commit produced no commit"], guardrails)
        pushed = self.repositories.push_branch(repo_path, branch=branch)
        if not pushed:
            return self._result(bot, "failed", branch, changed_files, optimizer, tests, empty_pr, empty_pr, baseline, candidate, ["git push failed"], guardrails)

        pr = self.prs.create_pr(
            repo=bot.github_repo,
            title=f"Bot assessor weekly optimization for {bot.name}",
            body=render_pr_body(bot, changed_files, baseline, candidate, tests, guardrails),
            head=branch,
            base=bot.default_branch,
            labels=["bot-assessor", "weekly-optimizer"],
            dry_run=False,
        )
        if not pr.ok:
            return self._result(bot, "failed", branch, changed_files, optimizer, tests, pr, empty_pr, baseline, candidate, [pr.error or "PR creation failed"], guardrails)

        merge = PublicationResult(ok=True, skipped=True)
        status = "pr_opened"
        if _can_auto_merge(bot, changed_files, guardrails, allow_auto_merge=self.options.allow_auto_merge):
            merge = self.prs.merge_pr(
                repo=bot.github_repo,
                number=pr.metadata.get("number"),
                commit_title=f"Bot assessor weekly optimization for {bot.name}",
                dry_run=False,
            )
            status = "auto_merged" if merge.ok else "failed"
        errors = [] if merge.ok else [merge.error or "auto-merge failed"]
        return self._result(bot, status, branch, changed_files, optimizer, tests, pr, merge, baseline, candidate, errors, guardrails)

    def _run_optimizer_command(self, bot: BotConfig, repo_path: Path, branch: str) -> CommandCheck:
        env = dict(bot.optimizer_env)
        env.update({"BOT_ASSESSOR_BOT_ID": bot.id, "BOT_ASSESSOR_BRANCH": branch, "BOT_ASSESSOR_MODE": "weekly_optimizer"})
        result = self.runner.run(bot.optimizer_command, cwd=repo_path, env=env, timeout_seconds=3600)
        return CommandCheck.from_result(result)

    def _run_candidate_generator(
        self,
        bot: BotConfig,
        repo_path: Path,
        branch: str,
        baseline: dict[str, BacktestResult],
        *,
        generated_at: datetime,
    ) -> CommandCheck:
        context = _candidate_context(bot, branch, baseline, generated_at=generated_at)
        result = generate_candidate(
            bot.candidate_generator or bot.id,
            repo_path=repo_path,
            bot_id=bot.id,
            context=context,
            generated_at=generated_at,
        )
        return CommandCheck(
            command=["bot-assessor", "generate-candidate", "--bot", bot.id, "--generator", bot.candidate_generator or bot.id],
            ok=result.ok,
            returncode=0 if result.ok else 1,
            output=result.output[-12000:],
            error=None if result.ok else result.error,
        )

    def _run_tests(self, bot: BotConfig, repo_path: Path) -> CommandCheck:
        if self.options.skip_tests:
            return CommandCheck.skipped_check("tests skipped by runtime option")
        if not bot.test_command:
            return CommandCheck.skipped_check("test_command is not configured")
        return CommandCheck.from_result(self.runner.run(bot.test_command, cwd=repo_path, env=bot.optimizer_env, timeout_seconds=3600))

    def _run_backtest_scenarios(self, bot: BotConfig, scenarios: list[OptimizationBacktestScenario], repo_path: Path) -> dict[str, BacktestResult]:
        return {
            scenario.name: self.backtests.run_command(
                scenario.command,
                repo_path=repo_path,
                setup_command=bot.setup_command,
                env=scenario.env,
                timeout_seconds=7200,
            )
            for scenario in scenarios
        }

    def _result(
        self,
        bot: BotConfig,
        status: str,
        branch: str | None,
        changed_files: list[str],
        optimizer: CommandCheck,
        tests: CommandCheck,
        pr: PublicationResult,
        merge: PublicationResult,
        baseline: dict[str, BacktestResult] | None = None,
        candidate: dict[str, BacktestResult] | None = None,
        errors: list[str] | None = None,
        guardrails: GuardrailDecision | None = None,
    ) -> BotOptimizationResult:
        fallback_reasons = errors or []
        if not fallback_reasons and optimizer.skipped and optimizer.error:
            fallback_reasons = [optimizer.error]
        return BotOptimizationResult(
            bot_id=bot.id,
            bot_name=bot.name,
            status=status,
            base_branch=bot.default_branch,
            branch=branch,
            changed_files=changed_files,
            optimizer=optimizer,
            tests=tests,
            guardrails=guardrails or GuardrailDecision(passed=status not in {"failed"}, reasons=fallback_reasons),
            baseline_backtests=baseline or {},
            candidate_backtests=candidate or {},
            pull_request=pr,
            merge=merge,
            errors=errors or [],
        )


def evaluate_guardrails(
    bot: BotConfig,
    baseline: dict[str, BacktestResult],
    candidate: dict[str, BacktestResult],
    tests: CommandCheck,
    *,
    skip_backtests: bool = False,
) -> GuardrailDecision:
    guardrails = bot.optimizer_guardrails
    reasons: list[str] = []
    if guardrails.get("require_tests", True):
        if tests.skipped:
            reasons.append("test_command is required but was skipped")
        elif not tests.ok:
            reasons.append("test_command failed")
    if guardrails.get("require_backtests", True) and skip_backtests:
        reasons.append("backtests are required but were skipped")
    if not skip_backtests:
        for name, candidate_result in candidate.items():
            baseline_result = baseline.get(name)
            reasons.extend(_evaluate_scenario(name, baseline_result, candidate_result, guardrails))
    return GuardrailDecision(passed=not reasons, reasons=reasons or ["guardrails passed"])


def _evaluate_scenario(name: str, baseline: BacktestResult | None, candidate: BacktestResult, guardrails: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if baseline is None or not baseline.ok:
        reasons.append(f"{name}: baseline backtest failed")
    if not candidate.ok:
        reasons.append(f"{name}: candidate backtest failed")
    if reasons:
        return reasons
    min_trades = int(guardrails.get("min_trades", 0))
    if min_trades and (candidate.total_trades is None or candidate.total_trades < min_trades):
        reasons.append(f"{name}: candidate trade count {candidate.total_trades} is below {min_trades}")
    if guardrails.get("require_pnl_improvement", True):
        min_delta = float(guardrails.get("min_total_pnl_delta", 0.0))
        if baseline.total_pnl is None or candidate.total_pnl is None:
            reasons.append(f"{name}: pnl metric missing")
        elif candidate.total_pnl <= baseline.total_pnl + min_delta:
            reasons.append(f"{name}: candidate pnl {candidate.total_pnl:.4f} did not beat baseline {baseline.total_pnl:.4f}")
    if guardrails.get("require_profit_factor_not_worse", False):
        min_pf_delta = float(guardrails.get("min_profit_factor_delta", 0.0))
        if baseline.profit_factor is None or candidate.profit_factor is None:
            reasons.append(f"{name}: profit factor metric missing")
        elif candidate.profit_factor < baseline.profit_factor + min_pf_delta:
            reasons.append(f"{name}: candidate profit factor {candidate.profit_factor:.4f} is below required threshold")
    min_candidate_pf = guardrails.get("min_candidate_profit_factor")
    if min_candidate_pf is not None:
        if candidate.profit_factor is None:
            reasons.append(f"{name}: candidate profit factor metric missing")
        elif candidate.profit_factor < float(min_candidate_pf):
            reasons.append(f"{name}: candidate profit factor {candidate.profit_factor:.4f} is below minimum {float(min_candidate_pf):.4f}")
    if guardrails.get("require_return_pct_not_worse", False):
        min_return_delta = float(guardrails.get("min_return_pct_delta", 0.0))
        if baseline.return_pct is None or candidate.return_pct is None:
            reasons.append(f"{name}: return metric missing")
        elif candidate.return_pct < baseline.return_pct + min_return_delta:
            reasons.append(f"{name}: candidate return {candidate.return_pct:.4f} did not meet baseline {baseline.return_pct:.4f}")
    if guardrails.get("require_win_rate_not_worse", False):
        min_win_delta = float(guardrails.get("min_win_rate_delta", 0.0))
        if baseline.win_rate is None or candidate.win_rate is None:
            reasons.append(f"{name}: win-rate metric missing")
        elif candidate.win_rate < baseline.win_rate + min_win_delta:
            reasons.append(f"{name}: candidate win rate {candidate.win_rate:.4f} did not meet baseline {baseline.win_rate:.4f}")
    max_trade_count_drop_pct = guardrails.get("max_trade_count_drop_pct")
    if max_trade_count_drop_pct is not None and baseline.total_trades is not None and candidate.total_trades is not None and baseline.total_trades > 0:
        drop_pct = (baseline.total_trades - candidate.total_trades) / baseline.total_trades
        if drop_pct > float(max_trade_count_drop_pct):
            reasons.append(f"{name}: candidate trade count dropped {drop_pct:.2%}, beyond guardrail")
    max_drawdown_worsening = guardrails.get("max_drawdown_worsening")
    if max_drawdown_worsening is not None:
        if baseline.max_drawdown is None or candidate.max_drawdown is None:
            reasons.append(f"{name}: drawdown metric missing")
        elif abs(candidate.max_drawdown) > abs(baseline.max_drawdown) + float(max_drawdown_worsening):
            reasons.append(f"{name}: candidate drawdown {candidate.max_drawdown:.4f} worsened beyond guardrail")
    max_candidate_drawdown = guardrails.get("max_candidate_drawdown")
    if max_candidate_drawdown is not None:
        if candidate.max_drawdown is None:
            reasons.append(f"{name}: candidate drawdown metric missing")
        elif abs(candidate.max_drawdown) > abs(float(max_candidate_drawdown)):
            reasons.append(f"{name}: candidate drawdown {candidate.max_drawdown:.4f} exceeds maximum {float(max_candidate_drawdown):.4f}")
    return reasons


def render_pr_body(
    bot: BotConfig,
    changed_files: list[str],
    baseline: dict[str, BacktestResult],
    candidate: dict[str, BacktestResult],
    tests: CommandCheck,
    guardrails: GuardrailDecision,
) -> str:
    lines = [f"# Weekly Optimization - {bot.name}", "", "Generated by bot-assessor phase 4.", ""]
    lines.append("## Changed Files")
    lines.extend([f"- `{path}`" for path in changed_files] or ["- None"])
    lines.append("")
    lines.append("## Checks")
    lines.append(f"- Tests: {_check_label(tests)}")
    lines.append(f"- Guardrails: {'passed' if guardrails.passed else 'failed'}")
    for reason in guardrails.reasons:
        lines.append(f"- {reason}")
    lines.append("")
    lines.append("## Backtests")
    lines.append("| Scenario | Baseline Trades | Candidate Trades | Baseline PnL | Candidate PnL | Baseline Return | Candidate Return | Baseline PF | Candidate PF | Baseline DD | Candidate DD |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for name, candidate_result in candidate.items():
        baseline_result = baseline.get(name)
        lines.append(
            "| "
            + " | ".join(
                [
                    name,
                    _metric(baseline_result.total_trades if baseline_result else None),
                    _metric(candidate_result.total_trades),
                    _metric(baseline_result.total_pnl if baseline_result else None),
                    _metric(candidate_result.total_pnl),
                    _metric(baseline_result.return_pct if baseline_result else None),
                    _metric(candidate_result.return_pct),
                    _metric(baseline_result.profit_factor if baseline_result else None),
                    _metric(candidate_result.profit_factor),
                    _metric(baseline_result.max_drawdown if baseline_result else None),
                    _metric(candidate_result.max_drawdown),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("Manual approval is required unless phase 5 auto-merge is explicitly enabled and all changed files match the bot allowlist.")
    return "\n".join(lines)


def render_optimization_markdown(results: list[BotOptimizationResult], *, generated_at: datetime) -> str:
    lines = [f"# Weekly Bot Optimizer - {generated_at.strftime('%Y-%m-%d %H:%M UTC')}", ""]
    lines.append("| Bot | Status | Changed Files | PR | Merge |")
    lines.append("| --- | --- | ---: | --- | --- |")
    for result in results:
        lines.append(
            f"| {result.bot_name} | {result.status} | {len(result.changed_files)} | {result.pull_request.url or '-'} | {result.merge.url or ('skipped' if result.merge.skipped else '-')} |"
        )
    for result in results:
        lines.extend(["", f"## {result.bot_name}", ""])
        if result.branch:
            lines.append(f"Branch: `{result.branch}`")
        if result.changed_files:
            lines.append("Changed files:")
            lines.extend(f"- `{path}`" for path in result.changed_files)
        lines.append("Guardrails:")
        lines.extend(f"- {reason}" for reason in result.guardrails.reasons)
        if result.errors:
            lines.append("Errors:")
            lines.extend(f"- {error}" for error in result.errors)
    return "\n".join(lines) + "\n"


def write_optimization_artifacts(artifact_dir: Path, results: list[BotOptimizationResult], markdown: str, *, generated_at: datetime) -> dict[str, str]:
    target = artifact_dir / generated_at.strftime("%Y-%m-%d")
    target.mkdir(parents=True, exist_ok=True)
    markdown_path = target / "weekly_optimizer.md"
    json_path = target / "weekly_optimizer.json"
    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps({"generated_at": generated_at.isoformat(), "results": [asdict(item) for item in results]}, indent=2, default=str), encoding="utf-8")
    return {"markdown": str(markdown_path), "json": str(json_path)}


def _scenario_configs(bot: BotConfig) -> list[OptimizationBacktestScenario]:
    if bot.optimizer_backtests:
        return [
            OptimizationBacktestScenario(
                name=str(raw.get("name") or f"scenario_{index + 1}"),
                command=list(raw.get("command") or bot.backtest_command),
                env={key: str(value) for key, value in dict(raw.get("env") or bot.backtest_env).items()},
            )
            for index, raw in enumerate(bot.optimizer_backtests)
        ]
    return [OptimizationBacktestScenario(name="default", command=bot.backtest_command, env=bot.backtest_env)]


def _candidate_context(bot: BotConfig, branch: str, baseline: dict[str, BacktestResult], *, generated_at: datetime) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "generated_at": generated_at.isoformat(),
        "bot_id": bot.id,
        "bot_name": bot.name,
        "branch": branch,
        "baseline_backtests": {name: _backtest_context(result) for name, result in baseline.items()},
        "guardrails": dict(bot.optimizer_guardrails),
    }


def _backtest_context(result: BacktestResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "total_trades": result.total_trades,
        "total_pnl": result.total_pnl,
        "return_pct": result.return_pct,
        "profit_factor": result.profit_factor,
        "win_rate": result.win_rate,
        "max_drawdown": result.max_drawdown,
    }


def _run_path_allowed(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch(normalized, pattern) for pattern in patterns)


def _disallowed_files(files: list[str], patterns: list[str]) -> list[str]:
    if not patterns:
        return []
    return [path for path in files if not _run_path_allowed(path, patterns)]


def _can_auto_merge(bot: BotConfig, changed_files: list[str], guardrails: GuardrailDecision, *, allow_auto_merge: bool) -> bool:
    if not allow_auto_merge or not bot.auto_merge_enabled or not guardrails.passed or not changed_files:
        return False
    if not bot.auto_merge_allowed_file_patterns:
        return False
    return not _disallowed_files(changed_files, bot.auto_merge_allowed_file_patterns)


def _guardrail_execution_failed(tests: CommandCheck, baseline: dict[str, BacktestResult], candidate: dict[str, BacktestResult]) -> bool:
    if not tests.skipped and not tests.ok:
        return True
    return any(not result.ok for result in [*baseline.values(), *candidate.values()])


def _check_label(check: CommandCheck) -> str:
    if check.skipped:
        return f"skipped ({check.error})"
    return "passed" if check.ok else "failed"


def _metric(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{value:.4f}"