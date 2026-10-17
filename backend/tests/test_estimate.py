from app.services.estimate import Estimate, estimate_debate, pricing_from_models

MOD = {"role": "moderator", "model_id": "m/mod", "display_name": "Host"}
PRO = {"role": "debater", "model_id": "m/pro", "display_name": "Alice"}
CON = {"role": "debater", "model_id": "m/con", "display_name": "Bob"}


def _conf(**overrides):
    base = {
        "topic": "Cats vs dogs",
        "language": "English",
        "participants": [MOD, PRO, CON],
        "num_rounds": 2,
        "length_preset": "short",
    }
    return {**base, **overrides}


def _estimate(conf, pricing=None, **kw):
    params = {
        "own_key": False,
        "tts_provider": None,
        "tts_price_per_1k": 0.15,
        "markup": 1.2,
    }
    params.update(kw)
    return estimate_debate(conf, pricing or {}, **params)


def test_turn_count_and_length():
    est = _estimate(_conf())
    # 2 rounds x (moderator + 2 debaters) + verdict
    assert est.turns == 7
    assert est.words > 0
    assert est.duration_ms > 0
    assert est.render_ms < est.duration_ms
    assert est.tts_chars > est.words


def test_free_models_cost_nothing():
    est = _estimate(_conf())
    assert est.llm_cost_usd == 0
    assert est.credits_cost_usd == 0


def test_paid_models_cost_and_markup():
    pricing = {"m/pro": (0.000001, 0.000002), "m/con": (0.000001, 0.000002)}
    est = _estimate(_conf(), pricing)
    assert est.llm_cost_usd > 0
    assert abs(est.credits_cost_usd - est.llm_cost_usd * 1.2) < 1e-9
    own = _estimate(_conf(), pricing, own_key=True)
    assert own.llm_cost_usd == est.llm_cost_usd
    assert own.credits_cost_usd == 0


def test_more_rounds_cost_more():
    pricing = {"m/pro": (0.000001, 0.000002), "m/con": (0.000001, 0.000002)}
    two = _estimate(_conf(num_rounds=2), pricing)
    three = _estimate(_conf(num_rounds=3), pricing)
    assert three.turns > two.turns
    assert three.llm_cost_usd > two.llm_cost_usd
    assert three.duration_ms > two.duration_ms


def test_premium_voices_add_tts_cost():
    edge = _estimate(_conf(), tts_provider="edge")
    premium = _estimate(_conf(), tts_provider="elevenlabs")
    assert edge.tts_cost_usd == 0
    assert premium.tts_cost_usd > 0
    assert premium.credits_cost_usd == premium.tts_cost_usd


def test_pricing_from_models_parses_strings():
    pricing = pricing_from_models(
        [
            {"id": "a", "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
            {"id": "b", "pricing": {"prompt": "bad", "completion": "0"}},
            {"id": "c", "pricing": {}},
        ]
    )
    assert pricing["a"] == (0.000001, 0.000002)
    assert "b" not in pricing
    assert pricing["c"] == (0.0, 0.0)


def test_as_dict_round_trips():
    est = _estimate(_conf())
    assert isinstance(est, Estimate)
    assert set(est.as_dict()) >= {"turns", "credits_cost_usd", "duration_ms"}


def test_own_tts_key_keeps_voices_off_credits():
    paid = _estimate(_conf(), tts_provider="elevenlabs")
    own = _estimate(_conf(), tts_provider="elevenlabs", own_tts_key=True)
    assert paid.tts_cost_usd > 0
    assert own.tts_cost_usd == paid.tts_cost_usd
    assert own.credits_cost_usd == round(paid.credits_cost_usd - paid.tts_cost_usd, 6)


def test_fact_check_and_ai_pictures_add_credits():
    conf = _conf(
        media_plan={"visuals": True, "images": "ai", "outputs": ["audio"]}, fact_check=True
    )
    pricing = {"openai/gpt-4o-mini": (0.0, 0.0)}
    est = _estimate(conf, pricing, fact_check_price=0.006, image_price=0.009, max_images=3)
    debater_turns = 4  # 2 rounds x 2 debaters
    assert est.factcheck_cost_usd == round(debater_turns * 0.006, 6)
    assert est.images_cost_usd == round(3 * 0.009, 6)
    assert est.credits_cost_usd == round((est.factcheck_cost_usd + est.images_cost_usd) * 1.2, 6)
    # An own OpenRouter key pays the fact-checks; AI pictures still come from the balance.
    own = _estimate(
        conf, pricing, own_key=True, fact_check_price=0.006, image_price=0.009, max_images=3
    )
    assert own.credits_cost_usd == round(own.images_cost_usd * 1.2, 6)
    # Fact-checks need the visual scenes; pictures need the audio build.
    off = _estimate(
        _conf(media_plan={"visuals": False, "images": "ai", "outputs": ["audio"]}, fact_check=True),
        pricing,
        fact_check_price=0.006,
        image_price=0.009,
        max_images=3,
    )
    assert off.factcheck_cost_usd == 0 and off.images_cost_usd == 0
