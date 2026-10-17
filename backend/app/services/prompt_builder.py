"""Builds chat messages for moderator, debater and verdict turns."""

from typing import Any

from app.services.scheduler import ScheduledTurn

LENGTH_WORDS: dict[str, int] = {
    "very_short": 50,
    "short": 100,
    "medium": 250,
    "long": 500,
}

# The judge's verdict follows the turn length: it should round the debate off, not outweigh it
# (without a budget models wrote 250-480 words even after 50-word turns).
VERDICT_WORDS: dict[str, int] = {
    "very_short": 70,
    "short": 110,
    "medium": 170,
    "long": 260,
}
VERDICT_WORDS_PER_EXTRA_DEBATER = 25  # one more short paragraph for each debater beyond two

_TURN_INSTRUCTIONS: dict[str, str] = {
    "argument": "Present your full position on the topic with your strongest arguments.",
    "opening": (
        "This is your OPENING statement. Clearly state your position and lay out "
        "your two or three strongest arguments."
    ),
    "rebuttal": (
        "This is a REBUTTAL round. Directly address and counter the strongest points "
        "made by your opponents so far, then reinforce your own position."
    ),
    "closing": (
        "This is your CLOSING statement. Summarize why your position prevails, address "
        "the key objections raised, and finish with a memorable conclusion. "
        "Do not introduce new arguments."
    ),
}


def intensity_description(intensity: int) -> str:
    if intensity <= 2:
        return "Be extremely polite, calm, and academic."
    if intensity <= 4:
        return "Be measured, courteous, and thoughtful."
    if intensity <= 6:
        return "Be firm, engaging, and persuasive."
    if intensity <= 8:
        return "Be assertive, energetic, and pointed in your criticism."
    return "Be very passionate, dramatic, and intense, but respectful."


def length_words(length_preset: str) -> int:
    return LENGTH_WORDS.get(length_preset, LENGTH_WORDS["medium"])


def verdict_words(conf: dict[str, Any]) -> int:
    """Word budget of the judge's verdict (also used by the estimate)."""
    base = VERDICT_WORDS.get(str(conf.get("length_preset") or ""), VERDICT_WORDS["medium"])
    debaters = sum(1 for p in conf.get("participants") or [] if p.get("role") == "debater")
    return base + VERDICT_WORDS_PER_EXTRA_DEBATER * max(0, debaters - 2)


def _history_block(history: list[dict[str, Any]]) -> str:
    if not history:
        return "(No statements yet — the debate is just beginning.)"
    return "\n\n".join(f"{t['speaker_name']}: {t['text']}" for t in history)


def _context_block(conf: dict[str, Any]) -> str:
    """News background (trending topics: the models do not know recent news) and the user's
    angle, one line each, for the user message of every turn."""
    lines = ""
    news = conf.get("news") or {}
    if str(news.get("brief") or "").strip():
        outlet = str(news.get("outlet") or "").strip()
        title = str(news.get("title") or "").strip()
        source = ", ".join(part for part in (outlet, f'"{title}"' if title else "") if part)
        lines += f"News background{f' ({source})' if source else ''}: {news['brief'].strip()}\n"
    if conf.get("description"):
        lines += f"Context: {conf['description']}\n"
    return lines


def _participants_block(participants: list[dict[str, Any]]) -> str:
    return "\n".join(f"- {p.get('display_name')} ({p.get('role')})" for p in participants)


SPOKEN_TAGS = "[sarcastic] [laughs] [serious] [calm] [confident] [firm] [pause] [excited] [sighs]"


def _formatting_rules(output_style: str) -> str:
    if output_style == "spoken":
        return (
            "\nFORMATTING: This is a SPOKEN debate: your words will be voiced by text-to-speech and "
            "turned into a video. Write plain spoken prose only: no Markdown, no headers, no bullet "
            "or numbered lists, no emojis, no stage directions. Use short, punchy, quotable sentences "
            "and address your opponents by name. You may add at most one emotion cue per paragraph, "
            f"in square brackets at the start of a sentence, chosen only from: {SPOKEN_TAGS}."
        )
    return "\nFORMATTING: Use Markdown (bold, italics, short lists) to make your text readable."


def visuals_on(conf: dict[str, Any]) -> bool:
    """The show draws scenes while debaters speak (mirrors services.studio.visuals_enabled)."""
    plan = conf.get("media_plan") or {}
    return bool(plan) and bool(plan.get("visuals", True))


VISUAL_RULES = (
    "\nVISUALS: While you speak, the show draws charts, numbers and sketches on screen. You may "
    "request up to two visuals by writing [visual: what to show, with the exact figures or items] "
    "right after the sentence it illustrates, e.g. [visual: bar chart - wind power share: "
    "Denmark 50%, Germany 30%]. Requests are not read aloud. Only show facts you also state in "
    "your speech, and never invent figures."
)
DISPUTE_RULES = (
    "If one of these visuals is wrong or misleading — above all one the fact-check disputed — "
    "challenge it: say why in your speech and write [dispute <number>: <short reason>] right "
    "there (at most one per turn); the challenge is stamped on screen. Challenge only what you "
    "can explain."
)


def _common_rules(language: str, words: int, output_style: str = "markdown") -> str:
    return (
        f"\nIMPORTANT: Write your response in {language}."
        f"\nLength: about {words} words. Stay within this limit."
        + _formatting_rules(output_style)
        + "\nDo NOT prefix your response with your own name or role. Speak in first person."
    )


def build_debater_messages(
    conf: dict[str, Any],
    speaker: dict[str, Any],
    turn: ScheduledTurn,
    history: list[dict[str, Any]],
    visual_claims: str = "",
) -> list[dict[str, str]]:
    """`visual_claims`: numbered lines describing the opponents' on-screen scenes (with their
    fact-checks), which this speaker may challenge (services.studio)."""
    words = length_words(conf.get("length_preset", "medium"))
    language = conf.get("language", "English")
    persona = speaker.get("persona_custom") or "You are a skilled, well-informed debater."
    visuals = visuals_on(conf)

    system = (
        f"You are a participant in a structured debate. Your name is {speaker['display_name']}.\n"
        f"Persona and stance: {persona}\n"
        f"Style: {intensity_description(int(conf.get('intensity', 5)))}"
        + _common_rules(language, words, conf.get("output_style", "markdown"))
        + (VISUAL_RULES if visuals else "")
    )

    claims = (
        "\nVisuals your opponents have put on screen (with the studio's web fact-check where "
        f"available):\n{visual_claims}\n{DISPUTE_RULES}\n"
        if visuals and visual_claims.strip()
        else ""
    )
    user = (
        f"Debate topic: {conf.get('topic')}\n"
        + _context_block(conf)
        + f"\nParticipants:\n{_participants_block(conf.get('participants', []))}\n"
        f"\nDebate so far:\n{_history_block(history)}\n"
        f"{claims}"
        f"\nRound {turn.round_number} of {conf.get('num_rounds', 1)}. "
        f"{_TURN_INSTRUCTIONS.get(turn.turn_type, _TURN_INSTRUCTIONS['argument'])}\n"
        f"It is now your turn, {speaker['display_name']}."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_moderator_messages(
    conf: dict[str, Any],
    speaker: dict[str, Any],
    turn: ScheduledTurn,
    history: list[dict[str, Any]],
) -> list[dict[str, str]]:
    # Moderator interjections are short regardless of the debate length preset.
    words = min(length_words(conf.get("length_preset", "medium")), 120)
    language = conf.get("language", "English")
    persona = speaker.get("persona_custom") or "You are an impartial, articulate debate moderator."
    participants = conf.get("participants", [])
    debaters = [p for p in participants if p.get("role") == "debater"]
    num_rounds = int(conf.get("num_rounds", 1))

    system = (
        f"You are the moderator of a structured debate. Your name is {speaker['display_name']}.\n"
        f"{persona}\n"
        "You never argue for a side and never give your own opinion on the topic."
        + _common_rules(language, words, conf.get("output_style", "markdown"))
    )

    if turn.turn_type == "moderator_intro":
        task = (
            "Open the debate: welcome the audience, introduce the topic in one or two sentences, "
            "introduce each debater by name, briefly explain the format "
            f"({num_rounds} round(s)), and invite {debaters[0]['display_name']} to begin."
            if debaters
            else "Open the debate and introduce the topic."
        )
    else:
        task = (
            f"Round {turn.round_number - 1} has just ended. In a few sentences, neutrally summarize "
            f"the key points made so far, then open round {turn.round_number} of {num_rounds} "
            f"and hand over to {debaters[0]['display_name']}."
            if debaters
            else f"Open round {turn.round_number}."
        )

    user = (
        f"Debate topic: {conf.get('topic')}\n"
        + _context_block(conf)
        + f"\nParticipants:\n{_participants_block(participants)}\n"
        f"\nDebate so far:\n{_history_block(history)}\n"
        f"\nYour task: {task}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_verdict_messages(
    conf: dict[str, Any], history: list[dict[str, Any]], evidence: str = ""
) -> list[dict[str, str]]:
    """`evidence`: web fact-checks of the on-screen figures and the debaters' challenges
    (services.studio.verdict_evidence)."""
    language = conf.get("language", "English")
    words = verdict_words(conf)
    if conf.get("output_style") == "spoken":
        structure = (
            "You are speaking on camera: name the winner (or declare a draw) in your FIRST "
            "sentence and say in one sentence what decided it. Then give each debater, by name, one "
            "or two sentences: their strongest point and their main weakness. Plain spoken prose only: "
            "no Markdown, no headers, no lists, no emojis."
        )
    else:
        structure = (
            "Use exactly this structure and nothing else:\n"
            "**Winner: <name>** (or **Draw**), then one sentence on what decided it.\n"
            "Then one short paragraph per debater, starting with their name in bold: their "
            "strongest point and their main weakness (name a logical fallacy only if there was one)."
        )
    system = (
        "You are an expert, impartial debate judge.\n"
        "Analyze the full debate transcript provided by the user and deliver a verdict. Decide on "
        "argument strength, logic and persuasiveness.\n"
        f"{structure}\n"
        f"\nLength: about {words} words in total. This is a hard limit: the audience has just "
        "heard the debate, so judge it, do not retell it.\n"
        f"Write in {language}. Style: objective, professional, analytical."
    )
    evidence_block = (
        f"\n{evidence}\nWeigh accuracy: figures the fact-check refuted weaken a debater's case, a "
        "well-founded challenge strengthens it. Mention it briefly where it matters.\n"
        if evidence.strip()
        else ""
    )
    user = (
        f"Debate topic: {conf.get('topic')}\n"
        + _context_block(conf)
        + f"\nFull transcript:\n{_history_block(history)}\n"
        + evidence_block
        + "\nPlease deliver your final verdict now."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
