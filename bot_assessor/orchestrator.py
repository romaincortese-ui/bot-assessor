from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot_assessor.backtest import BacktestResult, BacktestRunner
from bot_assessor.command import CommandRunner
from bot_assessor.config import AssessorConfig, RuntimeOptions
from bot_assessor.logs import analyze_logs
from bot_assessor.overlays import build_safe_overlays, overlay_payload
from bot_assessor.portfolio import build_portfolio_summary
from bot_assessor.postmortem import build_postmortem
from bot_assessor.publishers import GitHubIssuePublisher, PublicationResult, RedisPublisher, TelegramNotifier
from bot_assessor.railway import RailwayDeploymentCollector, RailwayLogCollector
from bot_assessor.recommendations import build_recommendations
from bot_assessor.report import render_markdown, write_artifacts
from bot_assessor.repository import RepositoryManager
from bot_assessor.review import build_review, review_to_dict
from bot_assessor.runtime_status import RuntimeStatusCollector
from bot_assessor.variables import build_railway_variable_plan


@dataclass(frozen=True)
class AssessmentRunResult:
    reviews: list[dict[str, Any]]
    report_markdown: str
    artifacts: dict[str, str]
    github: PublicationResult
    telegram: PublicationResult
    redis_errors: list[str]


class BotAssessor:
    def __init__(
        self,
        config: AssessorConfig,
        options: RuntimeOptions,
        *,
        runner: CommandRunner | None = None,
        github: GitHubIssuePublisher | None = None,
        telegram: TelegramNotifier | None = None,
        redis_publisher: RedisPublisher | None = None,
    ) -> None:
        self.config = config
        self.options = options
        self.runner = runner or CommandRunner()
        self.repositories = RepositoryManager(self.runner, workdir=config.workdir)
        self.logs = RailwayLogCollector(self.runner)
        self.deployments = RailwayDeploymentCollector(self.runner)
        self.backtests = BacktestRunner(self.runner)
        self.github = github or GitHubIssuePublisher(repo=config.github_repo)
        self.telegram = telegram or TelegramNotifier()
        self.redis = redis_publisher or RedisPublisher()
        self.runtime_status = RuntimeStatusCollector(redis_url=getattr(self.redis, "redis_url", ""))

    def run(self) -> AssessmentRunResult:
        generated_at = datetime.now(timezone.utc)
        reviews: list[dict[str, Any]] = []
        redis_errors: list[str] = []
        for bot in self.config.bots:
            repo_path = self.repositories.ensure_repo(bot)
            git_info = self.repositories.git_info(repo_path)
            deployment = self.deployments.collect(bot, repo_path=repo_path)
            runtime_status = self.runtime_status.collect(bot, repo_path=repo_path)
            log_text = ""
            if not self.options.skip_logs:
                collection = self.logs.collect(bot, repo_path=repo_path, lines=bot.log_lines or self.config.log_lines, window_hours=self.config.window_hours)
                log_text = collection.text
                if not collection.ok and collection.error:
                    log_text += f"\nERROR collecting logs: {collection.error}"
                if runtime_status.ok and (not collection.ok or not log_text.strip()):
                    log_text += f"\n{runtime_status.text}"
            log_analysis = analyze_logs(log_text)
            backtest: BacktestResult | None = None
            if not self.options.skip_backtests:
                backtest = self.backtests.run(bot, repo_path=repo_path)
            portfolio = build_portfolio_summary(bot, logs=log_analysis, backtest=backtest, runtime_status=runtime_status.as_dict())
            postmortem = build_postmortem(bot, logs=log_analysis, backtest=backtest, portfolio=portfolio)
            recommendations = build_recommendations(bot, log_analysis, backtest, portfolio=portfolio, postmortem=postmortem)
            overlays = build_safe_overlays(bot, recommendations, generated_at=generated_at)
            variable_plan = build_railway_variable_plan(bot, recommendations, overlays, generated_at=generated_at)
            review = build_review(
                bot,
                generated_at=generated_at,
                window_hours=self.config.window_hours,
                git_info=git_info,
                logs=log_analysis,
                backtest=backtest,
                portfolio=portfolio.as_dict(),
                postmortem=postmortem.as_dict(),
                recommendations=recommendations,
                overlays=overlays,
                deployment_status=deployment.as_dict(),
                runtime_status=runtime_status.as_dict(),
                railway_variable_plan=variable_plan,
            )
            review_dict = review_to_dict(review)
            reviews.append(review_dict)
            review_publish = self.redis.publish_json(
                bot.compatible_review_redis_key,
                review_dict,
                enabled=self.options.publish_compatible_reviews and not self.options.dry_run,
            )
            if not review_publish.ok and review_publish.error:
                redis_errors.append(f"{bot.id}: review publish failed: {review_publish.error}")
            overlay_publish = self.redis.publish_json(
                bot.overlay_redis_key,
                overlay_payload(bot, overlays, generated_at=generated_at),
                enabled=self.options.apply_overlays and not self.options.dry_run,
            )
            if not overlay_publish.ok and overlay_publish.error:
                redis_errors.append(f"{bot.id}: overlay publish failed: {overlay_publish.error}")
        markdown = render_markdown(reviews, generated_at=generated_at, window_hours=self.config.window_hours)
        artifacts = write_artifacts(Path(self.config.artifact_dir), reviews, markdown, generated_at=generated_at)
        title = f"Daily bot assessment - {generated_at.strftime('%Y-%m-%d %H:%M UTC')}"
        github_result = self.github.publish(title=title, body=markdown, labels=self.config.report_labels, dry_run=self.options.dry_run)
        telegram_result = self.telegram.notify_daily_digest(reviews, report_url=github_result.url or artifacts.get("markdown"), dry_run=self.options.dry_run)
        return AssessmentRunResult(reviews, markdown, artifacts, github_result, telegram_result, redis_errors)