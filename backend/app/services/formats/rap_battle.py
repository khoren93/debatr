"""Rap battle: the MC opens, two rappers trade verses for 1-3 rounds (the second one starts round
2), the judge scores every round. Verses are a fixed number of lines (one per bar of the beat),
so the music build (media/music.py) can give each verse its own section of one track.

Rapper One raps for the topic, Rapper Two against it: a battle on a question, like a debate. The
texts are written to be performed, whatever the config's output style.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.services.formats.base import Format, Messages, Seat, debaters_of
from app.services.media import music
from app.services.prompt_builder import intensity_description
from app.services.scheduler import ScheduledTurn

# Lines (bars) per verse by the length preset ("long" only in configs saved before it was retired).
VERSE_LINES: dict[str, int] = {"very_short": 4, "short": 8, "medium": 12, "long": 16}
MC_INTRO_WORDS = 40
# The judge's score card: a line per round, shown on screen and in the transcript, never voiced.
CARD_WORDS_PER_ROUND = 14
CARD_TOTAL_WORDS = 6
VERSE = "verse"

# Delivery cues of the MC and the judge (ElevenLabs audio tags).
_TAGS = "[shouts] [excited] [whispers] [laughs] [mischievously]"
_LINE_JUNK = re.compile(r"^\s*(?:[-*•>]+|\d+[.)]|\(\d+\)|#+)\s*")
# A section label on a line of its own ("Verse 1:", "[Round 2 - GPT]"), never a lyric that starts
# with such a word ("Round one, I'm coming for your crown").
_LABEL = re.compile(
    r"^\s*[\[(]?\s*(?:verse|round|chorus|hook|intro|outro)(?:\s*\d+)?"
    r"(?:\s*[-\u2013\u2014:]\s*\S.{0,30})?\s*[\])]?\s*:?\s*$",
    re.I,
)
_EDGE_QUOTES = re.compile(r'^[\s"“”«»\']+|[\s"“”«»\']+$')
_CARD_LINE = re.compile(r"^\W*(?:round\s*\d+|total)\s*[:\-\u2013\u2014]", re.I)


def verse_lines(conf: Mapping[str, Any]) -> int:
    return VERSE_LINES.get(str(conf.get("length_preset") or ""), VERSE_LINES["short"])


def tidy_verse(text: str, lines: int) -> str:
    """The verse as lyrics: one line per bar, without numbering, labels, quotes, Markdown or
    [tags]; at most `lines` lines (a model that writes more is cut, fewer are kept)."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.replace("**", "").replace("__", "")
        line = re.sub(r"\[[^\]]{0,40}\]", " ", line)  # audio tags and [visual: …] markers
        line = _LINE_JUNK.sub("", line)
        line = _EDGE_QUOTES.sub("", line)
        line = " ".join(line.split())
        if not line or _LABEL.match(line):
            continue
        out.append(line)
    return "\n".join(out[:lines])


def _announcement(conf: Mapping[str, Any]) -> tuple[int, str]:
    """What the judge says out loud after the score card: (words, what), by the verse length.
    The round scores are on screen, so a longer battle hears more of the why, not more numbers."""
    rounds = int(conf.get("num_rounds") or 1)
    preset = str(conf.get("length_preset") or "")
    if preset == "very_short":
        return 15, "the final totals, then the winner"
    if preset in ("medium", "long"):
        return 12 + 12 * rounds, (
            "one quick line per round: who took it and with what (say the round in words, no "
            "scores), then the final totals and the winner"
        )
    return 25, (
        "the final totals, the one moment that decided the battle in a few words, then the winner"
    )


def is_card_line(line: str, names: Sequence[str]) -> bool:
    """A line of the judge's score card: "Round 2: Claude 8, GPT 7 - why" or "Total: Claude 15,
    GPT 14" (a score for every rapper; an announcement that mentions a round has none)."""
    return bool(_CARD_LINE.match(line)) and all(
        re.search(rf"{re.escape(name)}\W{{0,3}}\d{{1,2}}\b", line, re.I) for name in names
    )


def _names(conf: Mapping[str, Any]) -> tuple[str, str]:
    rappers = debaters_of(list(conf.get("participants") or []))
    one = str(rappers[0].get("display_name") or "Rapper One") if rappers else "Rapper One"
    two = str(rappers[1].get("display_name") or "Rapper Two") if len(rappers) > 1 else "Rapper Two"
    return one, two


def _history(history: list[dict[str, Any]]) -> str:
    verses = [h for h in history if h.get("turn_type") == VERSE]
    if not verses:
        return "(No verses yet: you open the battle.)"
    return "\n\n".join(f"{h['speaker_name']}:\n{h['text']}" for h in verses)


def _context(conf: Mapping[str, Any]) -> str:
    lines = ""
    news = conf.get("news") or {}
    if str(news.get("brief") or "").strip():
        lines += f"News background: {str(news['brief']).strip()}\n"
    if conf.get("description"):
        lines += f"Context: {conf['description']}\n"
    return lines


class RapBattleFormat(Format):
    id = "rap_battle"
    name = "Rap battle"
    show = "battle"
    tagline = "Two models trade verses over one beat; the judge scores every round."
    host_label = "MC"
    seats = (Seat("Rapper One", side="for"), Seat("Rapper Two", side="against"))
    min_debaters = 2
    max_debaters = 2
    host_required = True
    max_rounds = 3
    sides = False
    visuals = False
    voices = "elevenlabs"
    soundtrack = "music"
    output_style = "spoken"
    verdict_scores = True
    voice_stability = 0.0  # the MC and the judge: the widest emotional range
    announcer_voices = True
    moderation_note = (
        "This is a rap battle: roasting the opposing rapper (an AI model) and its arguments, "
        "trash talk and bragging are expected and fine."
    )

    def schedule(self, conf: Mapping[str, Any]) -> list[ScheduledTurn]:
        people = list(conf.get("participants") or [])
        host = next((i for i, p in enumerate(people) if p.get("role") == "moderator"), None)
        rappers = [i for i, p in enumerate(people) if p.get("role") == "debater"][:2]
        out: list[ScheduledTurn] = []
        if host is not None:
            out.append(ScheduledTurn(0, 1, "moderator_intro", host))
        for round_number in range(1, int(conf.get("num_rounds") or 1) + 1):
            # The second rapper opens round 2: nobody always gets the last word.
            order = rappers if round_number % 2 else list(reversed(rappers))
            for speaker in order:
                out.append(ScheduledTurn(len(out), round_number, VERSE, speaker))
        return out

    def host_messages(
        self,
        conf: Mapping[str, Any],
        speaker: Mapping[str, Any],
        turn: ScheduledTurn,
        history: list[dict[str, Any]],
    ) -> Messages:
        one, two = _names(conf)
        rounds = int(conf.get("num_rounds") or 1)
        language = conf.get("language", "English")
        persona = speaker.get("persona_custom") or "You are a high-energy battle rap MC."
        system = (
            f"You are {speaker.get('display_name')}, the MC of a rap battle: the ring announcer "
            "who calls the fighters into the ring and the hype man who gets the crowd on its "
            f"feet.\n{persona}\n"
            "You never take a side, and nobody has rapped yet: never give a score or a "
            "winner. Your words are shouted over the beat's intro:\n"
            '- short punchy sentences, most of them ending in "!" or "?!";\n'
            '- hold the moment with "..." before each rapper\'s name, then hit the name in '
            "CAPITALS, like a ring announcer calling a fighter; write every name exactly as "
            "given, never respelled, stretched or translated;\n"
            "- put a delivery cue in square brackets before two or three of the sentences, "
            f"chosen only from: {_TAGS};\n"
            "- no Markdown, no lists, no emojis, no stage directions, no sound effects in words.\n"
            f"IMPORTANT: Write in {language}. At most {MC_INTRO_WORDS} words: every word must hit."
        )
        user = (
            f"Battle topic: {conf.get('topic')}\n"
            + _context(conf)
            + f"\nRappers: {one} raps FOR the topic, {two} raps AGAINST it (if the topic asks "
            f"'A or B?', {one} backs A and {two} backs B).\n"
            "\nIn this order: get the crowd going; the topic in one line (a long question cut "
            f"to its core); call {one} into the ring with their side; call {two} with theirs; "
            f"there will be {rounds} round{'s' if rounds != 1 else ''} and the judge will score "
            f"every round; hand the mic to {one}.\n"
            f"For example: [shouts] In this corner, rapping FOR... {one.upper()}!"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def debater_messages(
        self,
        conf: Mapping[str, Any],
        speaker: Mapping[str, Any],
        turn: ScheduledTurn,
        history: list[dict[str, Any]],
        visual_claims: str = "",
    ) -> Messages:
        lines = verse_lines(conf)
        one, two = _names(conf)
        me = str(speaker.get("display_name"))
        opponent = two if me == one else one
        side = "FOR" if me == one else "AGAINST"
        language = conf.get("language", "English")
        persona = speaker.get("persona_custom") or "You are a sharp, witty battle rapper."
        rounds = int(conf.get("num_rounds") or 1)
        system = (
            f"You are {me}, a battle rapper in a rap battle against {opponent}.\n"
            f"Persona: {persona}\n"
            f"Your side: you rap {side} the topic (if it asks 'A or B?', you back "
            f"{'A' if side == 'FOR' else 'B'}).\n"
            f"Style: {intensity_description(int(conf.get('intensity', 5)))}\n"
            f"\nWrite EXACTLY {lines} lines of rap lyrics: one line per bar, 8 to 14 syllables "
            "each, with strong end rhymes (couplets or alternating; rhyme different words, never "
            "a word with itself) and punchlines. Rap in the "
            "first person and talk to your opponent directly. Answer their last verse and turn "
            "their own lines against them; make your case on the topic.\n"
            "Roast your opponent's arguments, bars and AI persona, never real people. No slurs, "
            "no insults about race, religion, gender, sexuality or disability, no sexual content, "
            "no threats of violence.\n"
            f"Output only the {lines} lines, in {language}: no title, no labels like 'Verse 1', "
            "no numbering, no stage directions, no [tags], no Markdown, no emojis, no quotes "
            "around the lines."
        )
        user = (
            f"Battle topic: {conf.get('topic')}\n"
            + _context(conf)
            + f"\nThe battle so far:\n{_history(history)}\n"
            f"\nRound {turn.round_number} of {rounds}. Your {lines} lines, {me}:"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def verdict_messages(
        self, conf: Mapping[str, Any], history: list[dict[str, Any]], evidence: str = ""
    ) -> Messages:
        one, two = _names(conf)
        rounds = int(conf.get("num_rounds") or 1)
        language = conf.get("language", "English")
        words, what = _announcement(conf)
        system = (
            "You are the judge of a rap battle. Score every round: each rapper gets 1 to 10 for "
            "bars, rhymes, punchlines, answering the opponent and making their case on the topic. "
            "The rapper with the higher total wins; a draw only when the totals are equal.\n"
            "\nAnswer in two parts.\n"
            "Part 1, the score card. It is shown on screen and never spoken. One line per round, "
            "then the totals, in exactly this form, in English whatever the battle's language:\n"
            f"Round 1: {one} 8, {two} 7 - <why, at most 8 words in {language}>\n"
            f"Total: {one} <the sum of their round scores>, {two} <the sum of theirs>\n"
            "Part 2, after an empty line: your announcement, shouted over the beat's last bars "
            f"like a ring announcer reading the scorecards: {what}. Say the totals of your card. "
            f"End with the words for 'and the winner is...' in {language}, the '...' kept for "
            "the pause, and the winner's name in CAPITALS with an exclamation mark (for a draw: "
            "that it is a DRAW!). At most "
            f"{words} words, in {language}. Write the names exactly as given, never respelled or "
            "stretched. Put a delivery cue in square brackets before a sentence or two, chosen "
            f"only from: {_TAGS}.\n"
            "Plain text: no Markdown, no lists, no emojis."
        )
        user = (
            f"Battle topic: {conf.get('topic')}\n"
            f"{one} rapped FOR the topic, {two} AGAINST it, {rounds} round(s).\n"
            f"\nThe battle:\n{_history(history)}\n"
            "\nYour score card and announcement now."
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def verdict_words(self, conf: Mapping[str, Any]) -> int:
        rounds = int(conf.get("num_rounds") or 1)
        return CARD_WORDS_PER_ROUND * rounds + CARD_TOTAL_WORDS + self.voiced_verdict_words(conf)

    def voiced_verdict_words(self, conf: Mapping[str, Any]) -> int:
        return _announcement(conf)[0]

    def spoken_text(self, conf: Mapping[str, Any], turn_type: str, text: str) -> str:
        """The verdict without its score card (the score sheet shows it); the whole text when
        nothing else is left."""
        if turn_type != "verdict":
            return text
        names = _names(conf)
        lines = text.splitlines()
        # The card leads (or, from a model that got the order wrong, trails) the announcement.
        while lines and (not lines[0].strip() or is_card_line(lines[0], names)):
            lines.pop(0)
        while lines and (not lines[-1].strip() or is_card_line(lines[-1], names)):
            lines.pop()
        return "\n".join(lines).strip() or text

    def track_ms(self, conf: Mapping[str, Any], words_per_minute: int) -> int:
        """The plan the build would make, with the MC and the judge at their word budgets."""
        lines = "\n".join(["x"] * verse_lines(conf))
        flow = music.FLOWS[music.DEFAULT_FLOWS[0]]
        verses = [
            music.Verse(i, round_number, lines, flow)
            for i, round_number in enumerate(
                r for r in range(1, int(conf.get("num_rounds") or 1) + 1) for _ in range(2)
            )
        ]
        per_word = 60_000 / words_per_minute
        sections = music.build_plan(
            round(MC_INTRO_WORDS * per_word),
            verses,
            round(self.voiced_verdict_words(conf) * per_word),
        )
        return music.track_ms(sections)

    def finish_text(self, conf: Mapping[str, Any], turn: ScheduledTurn, text: str) -> str:
        return tidy_verse(text, verse_lines(conf)) if turn.turn_type == VERSE else text

    def catalogue(self) -> dict[str, Any]:
        """Plus the flows a rapper may take (`media_plan.flows`, in place of a voice)."""
        return {
            **super().catalogue(),
            "flows": [
                {"id": f.id, "label": f.label, "hint": f.hint, "voice": f.voice}
                for f in music.FLOWS.values()
            ],
            "default_flows": list(music.DEFAULT_FLOWS),
        }
