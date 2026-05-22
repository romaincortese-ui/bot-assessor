from pathlib import Path

from bot_assessor.backtest import BacktestRunner, parse_backtest_output
from bot_assessor.command import CommandResult
from bot_assessor.config import BotConfig


class RecordingRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self.results = results
        self.commands: list[list[str]] = []

    def run(self, command, *, cwd=None, env=None, timeout_seconds=900):
        self.commands.append(list(command))
        return self.results.pop(0)


def test_parse_json_summary_backtest_output() -> None:
    parsed = parse_backtest_output('{"summary":{"total_trades":2,"total_pnl":12.5,"profit_factor":1.8,"win_rate":0.5,"max_drawdown":-0.02}}')

    assert parsed["total_trades"] == 2
    assert parsed["total_pnl"] == 12.5
    assert parsed["profit_factor"] == 1.8
    assert parsed["win_rate"] == 0.5
    assert parsed["max_drawdown"] == -0.02


def test_parse_json_summary_preserves_zero_metrics() -> None:
    parsed = parse_backtest_output('{"report":{"total_trades":0,"total_pnl":0.0,"return_pct":0.0,"profit_factor":0.0,"win_rate":0.0,"max_drawdown":0.0}}')

    assert parsed["total_trades"] == 0
    assert parsed["total_pnl"] == 0.0
    assert parsed["return_pct"] == 0.0
    assert parsed["profit_factor"] == 0.0
    assert parsed["win_rate"] == 0.0
    assert parsed["max_drawdown"] == 0.0


def test_parse_last_metric_bearing_json_object() -> None:
    output = '\n'.join(
        [
            '{"backtest_run":{"total_trades":99}}',
            '{"signal_summary":{"best_signals":[]}}',
            '{"total_trades":4,"total_pnl":8.5,"profit_factor":2.0,"win_rate":0.75,"max_drawdown":-0.01}',
        ]
    )

    parsed = parse_backtest_output(output)

    assert parsed["total_trades"] == 4
    assert parsed["total_pnl"] == 8.5
    assert parsed["profit_factor"] == 2.0
    assert parsed["max_drawdown"] == -0.01


def test_parse_text_backtest_output() -> None:
    parsed = parse_backtest_output("trades=3 wins=2 losses=1 win_rate=66.67%\npnl=4.20 return=1.40% pf=2.10 max_dd=-3.00%")

    assert parsed["total_trades"] == 3
    assert parsed["total_pnl"] == 4.2
    assert round(parsed["return_pct"], 6) == 0.014
    assert parsed["profit_factor"] == 2.1
    assert parsed["max_drawdown"] == -0.03


def test_backtest_runner_runs_setup_before_backtest(tmp_path: Path) -> None:
    runner = RecordingRunner(
        [
            CommandResult(["python", "-m", "pip", "install", "-r", "requirements.txt"], str(tmp_path), 0, "installed", ""),
            CommandResult(["python", "run_daily_calibration.py"], str(tmp_path), 0, "trades=1 pnl=2.50 pf=1.20", ""),
        ]
    )
    bot = BotConfig(
        id="gold",
        name="Gold Bot",
        github_repo="romaincortese-ui/gold-bot",
        setup_command=["python", "-m", "pip", "install", "-r", "requirements.txt"],
        backtest_command=["python", "run_daily_calibration.py"],
    )

    result = BacktestRunner(runner).run(bot, repo_path=tmp_path)

    assert result.ok is True
    assert runner.commands == [
        ["python", "-m", "pip", "install", "-r", "requirements.txt"],
        ["python", "run_daily_calibration.py"],
    ]
    assert result.total_trades == 1


def test_backtest_runner_stops_when_setup_fails(tmp_path: Path) -> None:
    runner = RecordingRunner(
        [CommandResult(["python", "-m", "pip", "install", "-r", "requirements.txt"], str(tmp_path), 1, "", "missing package")]
    )
    bot = BotConfig(
        id="gold",
        name="Gold Bot",
        github_repo="romaincortese-ui/gold-bot",
        setup_command=["python", "-m", "pip", "install", "-r", "requirements.txt"],
        backtest_command=["python", "run_daily_calibration.py"],
    )

    result = BacktestRunner(runner).run(bot, repo_path=tmp_path)

    assert result.ok is False
    assert result.error is not None
    assert "setup_command failed" in result.error
    assert runner.commands == [["python", "-m", "pip", "install", "-r", "requirements.txt"]]