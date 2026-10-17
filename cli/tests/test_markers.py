import pytest

from debatr.markers import StreamedTurn, hide_studio_markers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Cars pollute. [visual: smog over a city] Next.", "Cars pollute. Next."),
        ("Wrong. [Dispute 2: the figure is from 1990]", "Wrong."),
        ("Typing [vis", "Typing"),
        ("Typing [ d", "Typing"),
        ("A list [1] stays", "A list [1] stays"),
        ("Brackets [vx] stay", "Brackets [vx] stay"),
        ("[thoughtful] Spoken tags stay", "[thoughtful] Spoken tags stay"),
    ],
)
def test_hide_studio_markers(text: str, expected: str):
    assert hide_studio_markers(text) == expected


def stream(*chunks: str) -> tuple[StreamedTurn, str]:
    turn = StreamedTurn()
    return turn, "".join(turn.feed(c) for c in chunks)


def test_a_marker_split_across_chunks_never_reaches_the_screen():
    turn, shown = stream("Cars pollute", ". [", "vis", "ual: smog", "] Next", " point.")
    assert "[" not in shown and "smog" not in shown
    assert shown == "Cars pollute. Next point."[: len(shown)]
    assert turn.finish("Cars pollute. Next point.") == shown_rest(
        "Cars pollute. Next point.", shown
    )


def shown_rest(final: str, shown: str) -> str:
    return final[len(shown) :]


def test_trailing_blanks_and_a_lone_bracket_wait_for_the_next_chunk():
    turn = StreamedTurn()
    assert turn.feed("Hello ") == "Hello"
    assert turn.feed("[") == ""
    assert turn.feed("1] world") == " [1] world"


def test_leading_whitespace_is_dropped():
    _, shown = stream("\n\n  Hi", " there")
    assert shown == "Hi there"


def test_finish_prints_the_whole_turn_when_nothing_streamed():
    assert StreamedTurn().finish("  Saved text.  ") == "Saved text."


def test_finish_never_repeats_text_when_the_server_tidied_it():
    turn, shown = stream("One. [visual: x]. Two")
    assert shown == "One.. Two"  # the browser shows the same until the turn is saved
    assert turn.finish("One. Two") == ""


def test_finish_without_final_flushes_the_held_back_tail():
    turn, shown = stream("Ends with [")
    assert shown == "Ends with"
    assert turn.finish() == " ["  # no marker came after all
