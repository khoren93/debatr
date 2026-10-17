from app.services.prompt_builder import build_debater_messages, build_verdict_messages
from app.services.scheduler import ScheduledTurn

CONF = {
    "topic": "T",
    "language": "English",
    "length_preset": "short",
    "participants": [{"display_name": "Nova", "role": "debater"}],
    "num_rounds": 1,
}
SPEAKER = {"display_name": "Nova", "persona_custom": "p"}
TURN = ScheduledTurn(0, 1, "argument", 0)


def test_spoken_style_replaces_markdown_rules() -> None:
    system = build_debater_messages({**CONF, "output_style": "spoken"}, SPEAKER, TURN, [])[0][
        "content"
    ]
    assert "no Markdown" in system and "[sarcastic]" in system
    assert "Use Markdown" not in system

    default = build_debater_messages(CONF, SPEAKER, TURN, [])[0]["content"]
    assert "Use Markdown" in default


def test_spoken_verdict_names_winner_first() -> None:
    system = build_verdict_messages({**CONF, "output_style": "spoken"}, [])[0]["content"]
    assert "FIRST" in system and "**Winner" not in system
    assert "**Winner: <name>**" in build_verdict_messages(CONF, [])[0]["content"]
