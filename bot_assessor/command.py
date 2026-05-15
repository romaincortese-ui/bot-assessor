from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    cwd: str | None
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def combined_output(self) -> str:
        if self.stderr:
            return f"{self.stdout}\n{self.stderr}".strip()
        return self.stdout


class CommandRunner:
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout_seconds: int = 900,
    ) -> CommandResult:
        merged_env = os.environ.copy()
        if env:
            merged_env.update({key: str(value) for key, value in env.items()})
        prepared = list(command)
        working_dir = str(cwd) if cwd is not None else None
        try:
            completed = subprocess.run(
                prepared,
                cwd=working_dir,
                env=merged_env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode(errors="replace")
            stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode(errors="replace")
            message = f"Command timed out after {timeout_seconds}s"
            return CommandResult(prepared, working_dir, 124, stdout or "", "\n".join(part for part in [stderr, message] if part))
        except FileNotFoundError as exc:
            return CommandResult(prepared, working_dir, 127, "", str(exc))
        return CommandResult(prepared, working_dir, completed.returncode, completed.stdout, completed.stderr)