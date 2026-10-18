import pytest
from conftest import DEBATE_ID, detail

from debatr.debate import (
    FREE_MODEL,
    Debater,
    build_config,
    digest,
    parse_debate_ref,
    round_heading,
    side_tags,
    total_turns,
    transcript_markdown,
)


def test_defaults_match_the_wizard():
    config = build_config("  Cats   or dogs? ", [Debater(), Debater()])
    assert config["topic"] == "Cats or dogs?"
    host, first, second = config["participants"]
    assert (host["role"], host["display_name"], host["model_id"]) == (
        "moderator",
        "The Host",
        FREE_MODEL,
    )
    assert (first["display_name"], second["display_name"]) == ("Nova", "Atlas")
    assert "in favor" in first["persona_custom"] and "against" in second["persona_custom"]
    assert config["auto_publish"] is False
    assert config["output_style"] == "markdown"
    assert "media_plan" not in config and "user_provider_key" not in config


def test_names_and_stances():
    config = build_config(
        "Q?",
        [
            Debater("a/b", name="Nova"),
            Debater("c/d", stance="A sceptical historian"),
            Debater("e/f"),
        ],
    )
    names = [p["display_name"] for p in config["participants"][1:]]
    assert names == ["Nova", "Atlas", "Quill"]  # a given name is not handed out twice
    assert config["participants"][2]["persona_custom"] == "A sceptical historian"
    assert "Position 3" in config["participants"][3]["persona_custom"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"debaters": []}, "at least one debater"),
        ({"debaters": [Debater(name="Nova"), Debater(name="nova")]}, "unique"),
        ({"debaters": [Debater(name="The Host")]}, "unique"),
        ({"debaters": [Debater()] * 8}, "At most 7 debaters"),
        ({"rounds": 0}, "Rounds"),
        ({"rounds": 11}, "Rounds"),
        ({"intensity": 11}, "Intensity"),
        ({"length": "epic"}, "Length"),
        ({"style": "poem"}, "Style"),
        ({"debaters": [Debater("has space")]}, "Not a model id"),
        ({"topic": "x" * 151}, "longer than 150 characters"),
    ],
)
def test_invalid_options(kwargs, message):
    args = {"debaters": [Debater(), Debater()], "topic": "Q?", **kwargs}
    with pytest.raises(ValueError, match=message):
        build_config(args.pop("topic"), args.pop("debaters"), **args)


def test_no_host_frees_a_seat():
    config = build_config("Q?", [Debater()] * 8, host_model=None)
    assert all(p["role"] == "debater" for p in config["participants"])


def test_media_plan_only_when_asked():
    scenes = build_config("Q?", [Debater()], scenes=True)
    assert scenes["media_plan"]["visuals"] is True and scenes["media_plan"]["outputs"] == []
    checked = build_config("Q?", [Debater()], fact_check=True)
    assert checked["media_plan"]["visuals"] is True and checked["fact_check"] is True
    voiced = build_config("Q?", [Debater()], audio=True, elevenlabs_key="sk_x")
    assert voiced["media_plan"]["outputs"] == ["audio", "video", "short"]
    assert voiced["output_style"] == "spoken"
    assert "user_tts_key" not in voiced  # only for ElevenLabs voices
    premium = build_config(
        "Q?", [Debater()], audio=True, voices="elevenlabs", elevenlabs_key=" sk_x "
    )
    assert premium["user_tts_key"] == "sk_x" and premium["media_plan"]["provider"] == "elevenlabs"
    keyed = build_config("Q?", [Debater()], openrouter_key=" sk-or-1 ")
    assert keyed["user_provider_key"] == "sk-or-1"


@pytest.mark.parametrize(
    ("ref", "kind", "value"),
    [
        (DEBATE_ID, "id", DEBATE_ID),
        (f"https://ai-debates.net/debate/{DEBATE_ID}", "id", DEBATE_ID),
        (f"ai-debates.net/debate/{DEBATE_ID}?tab=verdict", "id", DEBATE_ID),
        ("https://ai-debates.net/d/k3m9xq2p7w", "slug", "k3m9xq2p7w"),
        ("/d/k3m9xq2p7w", "slug", "k3m9xq2p7w"),
        ("k3m9xq2p7w", "slug", "k3m9xq2p7w"),
    ],
)
def test_parse_debate_ref(ref, kind, value):
    parsed = parse_debate_ref(ref)
    assert (parsed.kind, parsed.value) == (kind, value)


@pytest.mark.parametrize("ref", ["", "a b", "https://ai-debates.net/gallery", "../../etc/passwd"])
def test_parse_debate_ref_rejects(ref):
    with pytest.raises(ValueError):
        parse_debate_ref(ref)


def test_summaries():
    d = detail("completed")
    assert total_turns(d) == 4  # host + 2 debaters for 1 round + verdict
    assert side_tags(d["participants"]) == {
        "participant_0": "HOST",
        "participant_1": "PRO",
        "participant_2": "CON",
    }
    assert round_heading("round_2", "rebuttal") == "Round 2 · Rebuttal"
    assert round_heading("round_1", "moderator_intro") == "Round 1"
    assert round_heading("verdict", "verdict") == "Verdict"

    md = transcript_markdown(d)
    assert md.startswith("# Cats or dogs?")
    assert "### Nova · PRO · Round 1 · Argument" in md
    assert "**Winner: Nova**" in md

    out = digest(d, "https://x/debate/1")
    assert out["verdict"]["winner"] == "Nova"
    assert out["progress"] == {"turns_done": 4, "turns_total": 4}
    assert [t["speaker"] for t in out["turns"]] == ["The Host", "Nova", "Atlas", "⚖️ Verdict"]
    assert "transcript" not in out
    lean = digest(d, "u", turns="markdown")
    assert "turns" not in lean and "### Atlas" in lean["transcript"]
