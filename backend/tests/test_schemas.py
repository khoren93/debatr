import pytest
from pydantic import ValidationError

from app.schemas.schemas import DebateConfig

MOD = {"role": "moderator", "model_id": "m/mod", "display_name": "Moderator"}
DEB = {"role": "debater", "model_id": "m/deb", "display_name": "Alice"}


def test_minimal_config_defaults():
    cfg = DebateConfig.model_validate({"topic": "Cats vs dogs", "participants": [DEB]})
    assert cfg.num_rounds == 3
    assert cfg.length_preset == "medium"
    assert cfg.intensity == 5
    assert cfg.user_provider_key is None


def test_provider_key_is_excluded_from_persisted_config():
    cfg = DebateConfig.model_validate(
        {"topic": "t", "participants": [MOD, DEB], "user_provider_key": "sk-or-secret"}
    )
    dumped = cfg.model_dump(exclude={"user_provider_key"})
    assert "user_provider_key" not in dumped
    assert dumped["participants"][0]["role"] == "moderator"


@pytest.mark.parametrize(
    "participants",
    [
        [],
        [MOD],
        [MOD, MOD, DEB],
    ],
)
def test_participant_rules(participants):
    with pytest.raises(ValidationError):
        DebateConfig.model_validate({"topic": "t", "participants": participants})


@pytest.mark.parametrize("field,value", [("num_rounds", 0), ("num_rounds", 11), ("intensity", 0)])
def test_numeric_bounds(field, value):
    with pytest.raises(ValidationError):
        DebateConfig.model_validate({"topic": "t", "participants": [DEB], field: value})


def test_invalid_role_and_length_preset():
    with pytest.raises(ValidationError):
        DebateConfig.model_validate({"topic": "t", "participants": [{**DEB, "role": "judge"}]})
    with pytest.raises(ValidationError):
        DebateConfig.model_validate({"topic": "t", "participants": [DEB], "length_preset": "huge"})


def test_media_plan_defaults_and_persisted_excludes_transient_fields():
    cfg = DebateConfig.model_validate(
        {
            "topic": "t",
            "participants": [MOD, DEB],
            "media_plan": {"provider": "edge"},
            "draft": True,
            "user_provider_key": "sk-or-secret",
            "user_tts_key": "xi-secret",
        }
    )
    assert cfg.media_plan is not None
    assert cfg.media_plan.outputs == ["audio", "video", "short"]
    assert cfg.media_plan.quality == "1080p"
    stored = cfg.persisted()
    assert "user_provider_key" not in stored
    assert "user_tts_key" not in stored
    assert "draft" not in stored
    assert stored["media_plan"]["provider"] == "edge"


def test_publish_request_category_validation():
    from app.schemas.schemas import PublishRequest

    assert PublishRequest(category=" Tech ").category == "tech"
    assert PublishRequest(category="").category is None
    with pytest.raises(ValidationError):
        PublishRequest(category="sports")


def test_news_context_is_optional_and_needs_an_http_link():
    base = {"topic": "T", "participants": [DEB]}
    assert DebateConfig.model_validate(base).news is None
    news = {"brief": "What happened.", "outlet": "BBC", "url": "https://bbc.co.uk/x"}
    config = DebateConfig.model_validate({**base, "news": news})
    assert config.persisted()["news"]["outlet"] == "BBC"
    with pytest.raises(ValidationError):
        DebateConfig.model_validate({**base, "news": {"brief": "x", "url": "javascript:alert(1)"}})
    with pytest.raises(ValidationError):
        DebateConfig.model_validate({**base, "news": {"brief": ""}})
