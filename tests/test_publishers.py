from bot_assessor.publishers import GitHubIssuePublisher, TelegramNotifier


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
        if "api.github.com" in url:
            return FakeResponse(201, {"html_url": "https://github.com/owner/repo/issues/1"})
        return FakeResponse(200, {"ok": True})


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