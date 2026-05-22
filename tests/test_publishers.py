from bot_assessor.publishers import GitHubIssuePublisher, GitHubPullRequestPublisher, TelegramNotifier, build_daily_digest_message


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/pulls"):
            return FakeResponse(201, {"html_url": "https://github.com/owner/repo/pull/2", "number": 2})
        if url.endswith("/labels"):
            return FakeResponse(200, {"ok": True})
        if "api.github.com" in url:
            return FakeResponse(201, {"html_url": "https://github.com/owner/repo/issues/1"})
        return FakeResponse(200, {"ok": True})

    def put(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(200, {"merged": True, "html_url": "https://github.com/owner/repo/pull/2"})


def test_github_publisher_creates_issue() -> None:
    session = FakeSession()
    publisher = GitHubIssuePublisher(repo="owner/repo", token="token", session=session)

    result = publisher.publish(title="Daily", body="Body", labels=["daily"], dry_run=False)

    assert result.ok is True
    assert result.url == "https://github.com/owner/repo/issues/1"
    assert session.calls[0][1]["json"]["labels"] == ["daily"]


def test_telegram_skips_without_credentials() -> None:
    result = TelegramNotifier(token="", chat_id="").notify_report_ready(report_url="https://example.test")

    assert result.ok is True
    assert result.skipped is True


def test_telegram_sends_small_report_message() -> None:
    session = FakeSession()
    result = TelegramNotifier(token="token", chat_id="123", session=session).notify_report_ready(report_url="https://github.test/report")

    assert result.ok is True
    assert session.calls[0][1]["json"]["text"] == "New daily report ready: https://github.test/report"


def test_daily_digest_message_summarizes_portfolio_and_postmortems() -> None:
    message = build_daily_digest_message(
        [
            {
                "bot_name": "Indices Bot",
                "portfolio": {"currency": "GBP", "live_pnl_amount": -2.5, "risk_at_stop": 12.0, "margin_used": 50.0, "backtest_pnl": 15.0, "state": "attention"},
                "postmortem": {"severity": "high"},
            },
            {
                "bot_name": "Futures Bot",
                "portfolio": {"currency": "USD", "live_pnl_amount": 4.0, "risk_at_stop": 8.0, "margin_used": 20.0, "backtest_pnl": 25.0, "state": "healthy"},
                "postmortem": {"severity": "info"},
            },
        ],
        report_url="https://github.test/report",
    )

    assert "GBP: live P&L -£2.50" in message
    assert "USD: live P&L +$4.00" in message
    assert "Needs attention: Indices Bot" in message
    assert "High-severity post-mortems: Indices Bot" in message
    assert "Report: https://github.test/report" in message


def test_github_pr_publisher_creates_and_merges_pr() -> None:
    session = FakeSession()
    publisher = GitHubPullRequestPublisher(token="token", session=session)

    created = publisher.create_pr(
        repo="owner/repo",
        title="Optimize",
        body="Report",
        head="bot-assessor/weekly/bot/20260506",
        base="main",
        labels=["weekly-optimizer"],
    )
    merged = publisher.merge_pr(repo="owner/repo", number=created.metadata["number"], commit_title="Optimize")

    assert created.ok is True
    assert created.url == "https://github.com/owner/repo/pull/2"
    assert merged.ok is True
    assert session.calls[0][1]["json"]["head"] == "bot-assessor/weekly/bot/20260506"
    assert session.calls[-1][0].endswith("/pulls/2/merge")