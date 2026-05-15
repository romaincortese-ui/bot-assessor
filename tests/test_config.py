from bot_assessor.config import AssessorConfig


def test_default_config_maps_spot_bot_to_mexc_v2() -> None:
    config = AssessorConfig.load("assessor_config.example.json")
    spot = next(bot for bot in config.bots if bot.id == "mexc_spot")

    assert spot.github_repo == "romaincortese-ui/mexc-bot-v2"
    assert spot.railway_service == "mexc-bot-v2"