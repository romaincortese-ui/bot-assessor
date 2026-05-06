from bot_assessor.logs import analyze_logs


def test_analyze_logs_extracts_core_counts() -> None:
    text = """
    INFO trade_opened id=1
    WARNING stale macro state
    ERROR order_not_filled reason=INSUFFICIENT_MARGIN
    [MISSED_OPPORTUNITY] symbol=BTC_USDT side=LONG blocked_by=score_threshold theoretical_mfe_r=1.4
    Skipping scan skip_reason=no_signal
    """

    result = analyze_logs(text)

    assert result.total_lines == 5
    assert result.errors == 1
    assert result.warnings == 1
    assert result.order_opened == 1
    assert result.order_not_filled == 1
    assert result.skip_events == 1
    assert result.stale_data_hits == 1
    assert len(result.missed_opportunities) == 1
    assert result.top_blockers == [("score_threshold", 1)]