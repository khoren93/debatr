from app.services.markers import extract_markers, has_markers


def test_hints_are_cut_out_with_the_words_before_them():
    text = (
        "Wind already powers half of Denmark. [visual: bar chart - wind share: Denmark 50%, "
        "Germany 30%] And it keeps growing.\n\n**Second**, storage is cheap [Visual – battery prices "  # noqa: RUF001
        "down 90%]."
    )
    clean, hints, disputes = extract_markers(text)
    assert clean == (
        "Wind already powers half of Denmark. And it keeps growing.\n\n**Second**, storage is cheap."
    )
    assert [h.text for h in hints] == [
        "bar chart - wind share: Denmark 50%, Germany 30%",
        "battery prices down 90%",
    ]
    assert hints[0].after == "Wind already powers half of Denmark."
    assert hints[1].after.endswith("Second , storage is cheap") or hints[1].after.endswith(
        "Second, storage is cheap"
    )
    assert disputes == []


def test_disputes_and_limits():
    text = (
        "[visual: a] ignored too short? [visual: one chart] [visual: two] [visual: three] "
        "That chart is cherry-picked [dispute 2: the 90% figure is from 2010] [dispute #3 - also]"
    )
    clean, hints, disputes = extract_markers(text)
    assert "[" not in clean
    assert [h.text for h in hints] == ["one chart", "two"]  # max two; "a" is too short
    assert len(disputes) == 1
    assert disputes[0].number == 2 and disputes[0].reason == "the 90% figure is from 2010"


def test_text_without_markers_is_untouched():
    text = "[confident] Plain speech with [laughs] audio tags."
    assert not has_markers(text)
    clean, hints, disputes = extract_markers(text)
    assert clean == text and hints == [] and disputes == []


def test_marker_on_its_own_line():
    clean, hints, _ = extract_markers("First line.\n[visual: map of Europe]\nSecond line.")
    assert clean == "First line.\n\nSecond line." or clean == "First line.\nSecond line."
    assert hints[0].after == "First line."


def test_marker_between_sentence_ends_leaves_one_period():
    clean, hints, _ = extract_markers("Use rose by 30 percent. [visual: bars - 30%]. Then more...")
    assert clean == "Use rose by 30 percent. Then more..."
    assert hints[0].after == "Use rose by 30 percent."
