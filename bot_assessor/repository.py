from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from bot_assessor.command import CommandRunner
from bot_assessor.config import BotConfig


@dataclass(frozen=True)
class GitInfo:
    repo_path: str
    branch: str
    commit: str
    short_commit: str
    message: str
    dirty: bool


class RepositoryManager:
    def __init__(self, runner: CommandRunner, *, workdir: str | Path) -> None:
        self.runner = runner
        self.workdir = Path(workdir)

    def ensure_repo(self, bot: BotConfig) -> Path:
        if bot.repo_path:
            path = Path(bot.repo_path).expanduser().resolve()
            if path.exists():
                return path
        path = self.workdir / "repos" / bot.id
        path.parent.mkdir(parents=True, exist_ok=True)
        if (path / ".git").exists():
            self.runner.run(["git", "fetch", "origin", bot.default_branch], cwd=path, timeout_seconds=300)
            self.runner.run(["git", "checkout", bot.default_branch], cwd=path, timeout_seconds=120)
            self.runner.run(["git", "pull", "--ff-only", "origin", bot.default_branch], cwd=path, timeout_seconds=300)
            return path
        clone_url = self._clone_url(bot.github_repo)
        result = self.runner.run(["git", "clone", "--branch", bot.default_branch, clone_url, str(path)], timeout_seconds=600)
        if not result.ok:
            raise RuntimeError(f"git clone failed for {bot.id}: {result.stderr or result.stdout}")
        return path

    def git_info(self, repo_path: str | Path) -> GitInfo:
        path = Path(repo_path)
        branch = self._git(path, ["branch", "--show-current"]).strip() or "unknown"
        commit = self._git(path, ["rev-parse", "HEAD"]).strip()
        short_commit = self._git(path, ["rev-parse", "--short", "HEAD"]).strip()
        message = self._git(path, ["log", "-1", "--pretty=%s"]).strip()
        status = self._git(path, ["status", "--short"]).strip()
        return GitInfo(str(path), branch, commit, short_commit, message, dirty=bool(status))

    def _git(self, cwd: Path, args: list[str]) -> str:
        result = self.runner.run(["git", *args], cwd=cwd, timeout_seconds=120)
        return result.stdout if result.ok else ""

    @staticmethod
    def _clone_url(repo: str) -> str:
        token = os.getenv("BOT_ASSESSOR_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")
        if token:
            return f"https://x-access-token:{token}@github.com/{repo}.git"
        return f"https://github.com/{repo}.git"