from typing import Any

from app.models.models import Turn
from app.schemas.visuals import StatScene, assign_keys
from app.services.markers import DisputeMark, Hint
from app.services.media.visuals import PROMPT_VERSION
from app.services.studio import (
    brief_for,
    claims_prompt,
    claims_summary,
    disputes_by_key,
    fact_check_enabled,
    images_wanted,
    initial_visuals,
    live_pictures_cost,
    pick_for,
    picked_scenes,
    resolve_disputes,
    spoken_text,
    text_hash,
    turn_visuals_out,
    usable_plan,
    verdict_evidence,
    visual_claims,
    visuals_enabled,
)

CONF: dict[str, Any] = {
    "topic": "Energy",
    "participants": [
        {"role": "moderator", "display_name": "Host"},
        {"role": "debater", "display_name": "Nova"},
        {"role": "debater", "display_name": "Rex"},
    ],
    "media_plan": {"visuals": True, "images": "stock"},
    "fact_check": True,
}


def _stat(value: float, label: str) -> dict[str, Any]:
    return {"type": "stat", "anchor": "prices fell", "value": value, "suffix": "%", "label": label}


def _turn(seq: int, speaker: str, name: str, turn_type: str, text: str, **visuals: Any) -> Turn:
    return Turn(
        seq_index=seq,
        round_id="round_1",
        turn_type=turn_type,
        speaker_id=speaker,
        speaker_name=name,
        text=text,
        error=None,
        model_used="m",
        usage_json={},
        visuals_json=visuals,
    )


def _planned(
    seq: int, *scenes: dict[str, Any], checks: dict[int, Any] | None = None
) -> dict[str, Any]:
    parsed = assign_keys(seq, [StatScene.model_validate(s) for s in scenes])
    dumped: list[dict[str, Any]] = [s.model_dump(mode="json") for s in parsed]
    return {
        "status": "ready",
        "scenes": dumped,
        "picked": [s["key"] for s in dumped],
        "budget": len(dumped),
        "checks": {dumped[i]["key"]: c for i, c in (checks or {}).items()},
    }


def test_config_switches():
    assert visuals_enabled(CONF) and images_wanted(CONF) and fact_check_enabled(CONF)
    assert not visuals_enabled({"media_plan": None})
    assert not fact_check_enabled({"media_plan": {"visuals": False}, "fact_check": True})
    assert not images_wanted({"media_plan": {"visuals": True}})


def test_brief_takes_hints_and_the_last_rival():
    host = _turn(0, "participant_0", "Host", "moderator_intro", "Welcome to the show tonight.")
    nova = _turn(1, "participant_1", "Nova", "opening", "**Solar** is cheap.")
    rex = _turn(
        2,
        "participant_2",
        "Rex",
        "opening",
        "[firm] Not at night.",
        hints=[{"text": "map", "after": "x"}],
    )
    brief = brief_for(rex, [host, nova], CONF)
    assert brief.role == "debater" and brief.opponent == "Nova"
    assert brief.previous_text == "Solar is cheap."
    assert brief.text == "Not at night."
    assert brief.hints == (("map", "x"),) and brief.images
    assert brief.debaters == ("Nova", "Rex")
    assert (
        brief_for(host, [], CONF).role == "moderator" and brief_for(host, [], CONF).opponent is None
    )


def test_usable_plan_needs_the_same_text_and_version():
    text = "Prices fell ninety percent."
    stored = {
        **_planned(1, _stat(90, "fall")),
        "version": PROMPT_VERSION,
        "text_hash": text_hash(text),
    }
    assert [s.value for s in usable_plan(stored, text) or []] == [90]
    assert usable_plan(stored, "Another text.") is None
    assert usable_plan({**stored, "version": "0"}, text) is None
    assert usable_plan({**stored, "status": "designing"}, text) is None
    assert spoken_text("**Bold** [sarcastic] words") == "Bold words."


def test_claims_disputes_and_evidence():
    nova = _turn(
        1,
        "participant_1",
        "Nova",
        "opening",
        "Prices fell.",
        **_planned(
            1,
            _stat(90, "fall in solar prices"),
            _stat(40, "share of wind"),
            checks={0: {"verdict": "disputed", "note": "It was 80%."}},
        ),
    )
    rex = _turn(2, "participant_2", "Rex", "rebuttal", "No.", **_planned(2, _stat(12, "nights")))
    claims = visual_claims([nova, rex], "participant_2", "Rex")
    assert [c.number for c in claims] == [1, 2]
    assert claims[0].speaker_name == "Nova" and claims[0].check is not None
    prompt = claims_prompt(claims)
    assert (
        "[1] Nova: stat: 90% — fall in solar prices — fact-check: disputed (It was 80%.)" in prompt
    )
    assert "[2] Nova: stat: 40% — share of wind" in prompt
    # Own scenes are never offered.
    assert [c.speaker_name for c in visual_claims([nova, rex], "participant_1", "Nova")] == ["Rex"]

    disputes = resolve_disputes([DisputeMark(1, "cherry-picked"), DisputeMark(9, "x")], claims)
    assert disputes == [{"key": claims[0].key, "reason": "cherry-picked"}]
    closing = _turn(4, "participant_2", "Rex", "closing", "Done.", **initial_visuals([], disputes))
    by_key = disputes_by_key([nova, rex, closing])
    assert by_key[claims[0].key][0].by_name == "Rex" and by_key[claims[0].key][0].seq_index == 4

    evidence = verdict_evidence([nova, rex, closing])
    assert "Nova showed stat: 90% — fall in solar prices — disputed: It was 80%." in evidence
    assert "Rex challenged Nova's stat: 90% — fall in solar prices: cherry-picked" in evidence
    assert verdict_evidence([rex]) == ""

    summary = claims_summary([nova, rex, closing])
    assert summary == {
        "participant_1": {"checked": 1, "verified": 0, "disputed": 1, "unverified": 0}
    }


def test_turn_visuals_out_and_picks():
    plan = _planned(1, _stat(90, "fall"), _stat(40, "wind"))
    plan["picked"] = plan["picked"][:1]
    plan["checking"] = plan["picked"]
    plan["status"] = "checking"
    turn = _turn(1, "participant_1", "Nova", "opening", "x", **plan)
    out = turn_visuals_out(turn)
    assert out is not None and out.status == "checking"
    assert len(out.scenes) == 1 and out.scenes[0].checkable and out.scenes[0].check is None
    assert [s.value for s in picked_scenes(turn.visuals_json)] == [90]
    assert turn_visuals_out(_turn(2, "p", "P", "opening", "x")) is None
    hinted = _turn(3, "p", "P", "opening", "x", **initial_visuals([Hint("map", "a")], []))
    assert turn_visuals_out(hinted) is None  # hints alone are not shown

    # A turn picks from its own candidates after the turns before it.
    scenes = assign_keys(5, [StatScene.model_validate(_stat(v, "x")) for v in (1, 2)])
    assert len(pick_for(_turn(5, "p", "P", "opening", "x"), scenes, 1, [turn])) == 1


def test_live_pictures_are_summed_for_the_charge():
    turns = [
        _turn(1, "p1", "Nova", "opening", "x", usd={"images": 0.009, "images_count": 1}),
        _turn(2, "p2", "Rex", "opening", "x", usd={"design": 0.001}),
        _turn(3, "p1", "Nova", "rebuttal", "x", usd={"images": 0.018, "images_count": 2}),
    ]
    assert live_pictures_cost(turns) == (0.027, 3)
    assert live_pictures_cost([]) == (0.0, 0)
