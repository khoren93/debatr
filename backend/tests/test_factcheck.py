import json

from app.schemas.visuals import StatScene
from app.services.factcheck import build_check_messages, claim_sentence, parse_check

SPEECH = (
    "Thank you. Solar power got ten times cheaper in a single decade. Panels fell ninety percent "
    "since 2010, which changes the grid. Storage is next."
)


def test_claim_sentence_finds_the_anchor_and_adds_a_short_follow_up():
    assert claim_sentence(SPEECH, "Panels fell ninety percent") == (
        "Panels fell ninety percent since 2010, which changes the grid. Storage is next."
    )
    # No anchor: the first sentence (plus the next one, it is short).
    assert claim_sentence(SPEECH, "").startswith("Thank you. Solar power")
    assert claim_sentence("", "x") == ""


def test_parse_check_merges_sources_and_aliases():
    annotations = [
        {
            "type": "url_citation",
            "url_citation": {"url": "https://www.iea.org/report", "title": "IEA report"},
        },
        {"type": "url_citation", "url_citation": {"url": "https://ourworldindata.org/solar"}},
        {"type": "other"},
    ]
    text = (
        "```json\n"
        + json.dumps(
            {
                "verdict": "Mostly true",
                "note": "Module prices fell about 90%.",
                "sources": [
                    "https://www.iea.org/report",
                    "javascript:alert(1)",
                    {"url": "https://a.org/x"},
                ],
            }
        )
        + "\n```"
    )
    check = parse_check(text, annotations)
    assert check is not None
    assert check.verdict == "verified"
    assert [s.url for s in check.sources] == [
        "https://www.iea.org/report",
        "https://a.org/x",
        "https://ourworldindata.org/solar",
    ]
    assert check.sources[0].title == "IEA report"
    assert check.sources[1].title == "a.org"


def test_parse_check_rejects_unusable_replies():
    assert parse_check("no json here") is None
    assert parse_check('{"verdict": "maybe"}') is None
    disputed = parse_check('{"verdict": "false", "note": "It was 40%."}')
    assert disputed is not None and disputed.verdict == "disputed" and disputed.sources == []


def test_check_prompt_carries_the_claim():
    scene = StatScene.model_validate(
        {"type": "stat", "value": 90, "suffix": "%", "label": "fall in panel prices"}
    )
    from app.services.media.visuals import scene_summary

    messages = build_check_messages(
        topic="Energy",
        language="Russian",
        speaker="Nova",
        sentence="Panels fell ninety percent since 2010.",
        summary=scene_summary(scene),
    )
    user = messages[1]["content"]
    assert "Panels fell ninety percent" in user
    assert "stat: 90% — fall in panel prices" in user
    assert "in Russian" in user
