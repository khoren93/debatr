from debatr.styling import InlineMarkdown


def render(*chunks: str) -> list[tuple[str, str]]:
    md = InlineMarkdown()
    segments = [seg for chunk in chunks for seg in md.feed(chunk)] + md.finish()
    merged: list[tuple[str, str]] = []
    for text, style in segments:
        if merged and merged[-1][1] == style:
            merged[-1] = (merged[-1][0] + text, style)
        else:
            merged.append((text, style))
    return merged


def plain(*chunks: str) -> str:
    return "".join(text for text, _ in render(*chunks))


def test_bold_even_when_the_stars_are_split_across_chunks():
    assert render("Tea is *", "*calm*", "* and kind.") == [
        ("Tea is ", ""),
        ("calm", "bold"),
        (" and kind.", ""),
    ]


def test_headings_and_bullets():
    out = render("## Win", "ner\n", "- Nova\n", "* Atlas\n", "Done")
    assert out == [("Winner", "bold"), ("\n• Nova\n• Atlas\nDone", "")]


def test_a_heading_mark_split_from_its_text_waits():
    assert plain("#", "# Analysis\nText") == "Analysis\nText"


def test_unclosed_bold_ends_with_the_paragraph():
    assert render("**Loud\n\nquiet") == [("Loud", "bold"), ("\n\nquiet", "")]


def test_spoken_emotion_cue_is_shown_as_a_quiet_note():
    assert render("[thought", "ful] Let me explain.") == [
        ("(thoughtful) ", "dim italic"),
        ("Let me explain.", ""),
    ]


def test_plain_brackets_and_math_stay():
    assert plain("[1] Source and 2 * 3 = 6") == "[1] Source and 2 * 3 = 6"
    assert plain("A lone star at the end *") == "A lone star at the end *"
    assert plain("-1 degrees") == "-1 degrees"


def test_nested_bullets_keep_their_indent():
    assert plain("- Nova:\n", "  ", "- Appeal to nature\n") == "• Nova:\n  ◦ Appeal to nature\n"
