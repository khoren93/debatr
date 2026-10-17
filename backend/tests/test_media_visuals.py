from dataclasses import replace
from itertools import pairwise

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.geo import normalize_countries
from app.schemas.timeline import TimelineSegment, TimelineWord
from app.schemas.visuals import (
    BarsScene,
    BulletsScene,
    DefinitionScene,
    FlowScene,
    HeadlineScene,
    MapScene,
    MatrixScene,
    RankingScene,
    RebuttalScene,
    ScaleScene,
    Scene,
    ScoreboardScene,
    StatScene,
    TimelineVisual,
    VennScene,
    normalize_icon,
    parse_number,
)
from app.services.media.llm import extract_json
from app.services.media.visuals import (
    LEAD_MS,
    MIN_SCENE_MS,
    TurnBrief,
    align_scenes,
    announcement_index,
    build_briefs,
    build_director_messages,
    debater_label,
    diversify,
    is_grounded,
    make_room,
    parse_scenes,
    scene_budget,
    scoreboard_visual,
    spoken_numbers,
)

PER_WORD = 400  # ms per word in the synthetic segments


def _segment(text: str, start_ms: int = 10_000, seq: int = 3) -> TimelineSegment:
    words = [
        TimelineWord(w=t, s=i * PER_WORD, e=i * PER_WORD + PER_WORD - 50)
        for i, t in enumerate(text.split())
    ]
    return TimelineSegment(
        seq_index=seq,
        speaker_id="participant_1",
        speaker_name="Nova",
        round_id="round_1",
        turn_type="rebuttal",
        start_ms=start_ms,
        end_ms=start_ms + len(words) * PER_WORD,
        audio="turns/003.wav",
        text=text,
        words=words,
    )


def _word_ms(text: str, word: str) -> int:
    return text.split().index(word) * PER_WORD


SPEECH = (
    "Thank you. Solar power got ten times cheaper in a single decade, and that changes "
    "everything about the grid. First, panels are now the cheapest electricity ever built. "
    "Second, storage prices are falling just as fast. Third, every new coal plant becomes a "
    "stranded asset within years. My opponent claims that renewables are unreliable, but "
    "batteries already balance whole regions every single night. So the question is not "
    "whether we switch, but how fast we can build the transmission lines we need today."
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (42, 42.0),
        ("42%", 42.0),
        ("1 200", 1200.0),
        ("1,5", 1.5),
        ("1,500", 1500.0),
        ("1.234,5", 1234.5),
        ("1,234.5", 1234.5),
        ("$3.4 trillion", 3.4),
        ("\u221212", -12.0),
        ("2 000 000", 2_000_000.0),
    ],
)
def test_parse_number(raw: object, expected: float) -> None:
    assert parse_number(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [True, None, "many", float("nan"), 1e16, [1]])
def test_parse_number_rejects(raw: object) -> None:
    with pytest.raises(ValueError):
        parse_number(raw)


def test_normalize_icon_uses_catalogue_and_aliases() -> None:
    assert normalize_icon("Money") == "money"
    assert normalize_icon("ai") == "robot"
    assert normalize_icon("climate") == "earth"
    assert normalize_icon("unicorn") is None
    assert normalize_icon(5) is None


def test_scene_models_clip_instead_of_rejecting() -> None:
    scene = TypeAdapter(Scene).validate_python(
        {
            "type": "stat",
            "value": "73%",
            "suffix": "%",
            "label": "x" * 300,
            "trend": "sideways",
            "icon": "unicorn",
        }
    )
    assert isinstance(scene, StatScene)
    assert scene.value == 73
    assert len(scene.label) == 90 and scene.label.endswith("…")
    assert scene.trend is None and scene.icon is None


def test_scene_models_cut_long_lists() -> None:
    items = [{"label": f"L{i}", "value": i + 1} for i in range(10)]
    scene = TypeAdapter(Scene).validate_python({"type": "bars", "items": items})
    assert isinstance(scene, BarsScene)
    assert len(scene.items) == 6


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "bars", "items": [{"label": "only", "value": 1}]},
        {"type": "pie", "items": [{"label": "a", "value": 5}, {"label": "b", "value": -1}]},
        {"type": "proportion", "count": 3, "total": 1000, "label": "x"},
        {"type": "proportion", "count": 7, "total": 5, "label": "x"},
        {"type": "icons", "items": [{"icon": "unicorn", "label": "x"}]},
        {"type": "video", "url": "https://example.com"},
    ],
)
def test_invalid_scenes_are_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Scene).validate_python(bad)


def test_parse_scenes_tolerates_noise_and_aliases() -> None:
    reply = """```json
    {"scenes": [
      {"type": "bar_chart", "items": [{"label": "2014", "value": 10}, {"label": "2024", "value": "1"}]},
      "not a scene",
      {"type": "cycle", "steps": [{"label": "Cheaper"}, {"label": "More demand"}]},
      {"type": "bars", "items": []},
      {"type": "headline", "text": "**Ten times cheaper**"}
    ]}
    ```"""
    scenes = parse_scenes(extract_json(reply), limit=4)
    assert [s.type for s in scenes] == ["bars", "flow", "headline"]
    assert isinstance(scenes[1], FlowScene) and scenes[1].layout == "cycle"
    assert scenes[2].text == "Ten times cheaper"


def test_parse_scenes_respects_the_limit_and_shapes() -> None:
    many = [{"type": "headline", "text": f"Idea {i}"} for i in range(6)]
    assert len(parse_scenes({"scenes": many}, limit=2)) == 2
    assert len(parse_scenes(many, limit=3)) == 3
    assert parse_scenes(None, limit=3) == []
    assert parse_scenes({"scenes": "nope"}, limit=3) == []


def test_scene_budget_scales_with_length_and_role() -> None:
    assert scene_budget("short reply", "debater") == 0
    long = " ".join(["word"] * 150)  # ~58 s of speech
    assert scene_budget(long, "debater") == 3
    assert scene_budget(" ".join(["word"] * 1000), "debater") == 4
    assert scene_budget(" ".join(["word"] * 1000), "judge") == 2
    assert scene_budget(long, "moderator") == 1
    assert scene_budget(" ".join(["word"] * 20), "moderator") == 0


def test_director_prompt_carries_rules_context_and_budget() -> None:
    brief = TurnBrief(
        seq_index=3,
        speaker_id="participant_1",
        speaker_name="Nova",
        role="debater",
        turn_type="rebuttal",
        text=SPEECH,
        previous_text="Renewables are unreliable. " * 200,
        opponent="Atlas",
    )
    messages = build_director_messages(brief, topic="Solar", language="Russian", budget=3)
    system, user = messages[0]["content"], messages[1]["content"]
    assert "Never invent" in system and "rebuttal" in system and "money" in system
    assert "MUST have" in system
    assert "All visible text in Russian" in system
    assert "The opponent (Atlas) said just before" in user
    assert "Design up to 3 scenes, then one spare scene" in user
    assert len(user) < len(SPEECH) + 2200  # the opponent's turn is truncated


def test_align_places_scene_at_its_anchor() -> None:
    seg = _segment(SPEECH)
    scenes = parse_scenes(
        [
            {
                "type": "stat",
                "value": 10,
                "suffix": "x",
                "label": "cheaper",
                "anchor": "ten times cheaper in",
            }
        ],
        limit=3,
    )
    [visual] = align_scenes(scenes, seg)
    assert visual.anchored
    assert visual.start_ms == seg.start_ms + _word_ms(SPEECH, "ten") - LEAD_MS
    assert visual.end_ms - visual.start_ms >= MIN_SCENE_MS
    assert visual.id == "v3_0" and visual.speaker_id == "participant_1"


def test_align_reveals_items_on_their_phrases() -> None:
    seg = _segment(SPEECH)
    scenes = parse_scenes(
        [
            {
                "type": "bullets",
                "anchor": "First, panels are now",
                "items": [
                    {"text": "Cheapest power", "anchor": "panels are now the cheapest"},
                    {"text": "Storage falls", "anchor": "storage prices are falling"},
                    {"text": "Coal stranded", "anchor": "missing words entirely here"},
                ],
            }
        ],
        limit=3,
    )
    [visual] = align_scenes(scenes, seg)
    assert isinstance(visual.scene, BulletsScene)
    first, second, third = visual.item_ms
    assert first == seg.start_ms + _word_ms(SPEECH, "panels") - 120
    assert second == seg.start_ms + _word_ms(SPEECH, "storage") - 120
    assert third > second  # not found: placed after the located ones
    assert visual.end_ms >= third + 1200


def test_align_rebuttal_reveals_response_on_its_phrase() -> None:
    seg = _segment(SPEECH)
    scenes = parse_scenes(
        [
            {
                "type": "rebuttal",
                "claim": "Renewables are unreliable",
                "response": "Batteries balance regions",
                "anchor": "My opponent claims that",
                "response_anchor": "batteries already balance whole",
            }
        ],
        limit=2,
    )
    [visual] = align_scenes(scenes, seg)
    assert isinstance(visual.scene, RebuttalScene)
    assert visual.item_ms[0] == visual.start_ms
    assert visual.item_ms[1] == seg.start_ms + _word_ms(SPEECH, "batteries") - 120


def test_align_without_anchor_spreads_scenes_and_marks_them() -> None:
    seg = _segment(SPEECH)
    scenes = parse_scenes(
        [
            {"type": "headline", "text": "One", "anchor": "nothing like this is said"},
            {"type": "headline", "text": "Two"},
        ],
        limit=2,
    )
    visuals = align_scenes(scenes, seg)
    assert [v.anchored for v in visuals] == [False, False]
    duration = seg.end_ms - seg.start_ms
    assert visuals[1].start_ms == seg.start_ms + round(duration / 2)


def test_align_resolves_overlaps_and_short_leftovers() -> None:
    seg = _segment(SPEECH)
    scenes = parse_scenes(
        [
            {"type": "headline", "text": "A", "anchor": "Solar power got ten"},
            {"type": "headline", "text": "B", "anchor": "times cheaper in a"},  # 1 s later
            {"type": "headline", "text": "C", "anchor": "Third, every new coal"},
        ],
        limit=3,
    )
    visuals = align_scenes(scenes, seg)
    texts = [v.scene.text for v in visuals]  # type: ignore[union-attr]
    assert texts == ["B", "C"]  # A was squeezed below the minimum and dropped
    for a, b in pairwise(visuals):
        assert a.end_ms <= b.start_ms


def test_align_keeps_scenes_inside_the_turn() -> None:
    seg = _segment(SPEECH)
    scenes = parse_scenes(
        [{"type": "quote", "text": "Build", "anchor": "lines we need today."}], limit=1
    )
    [last] = align_scenes(scenes, seg)  # the closing words: shown from a little earlier
    assert last.end_ms == seg.end_ms + 400
    assert last.end_ms - last.start_ms == MIN_SCENE_MS
    scenes = parse_scenes(
        [{"type": "stat", "value": 1, "label": "x", "anchor": "So the question is"}], limit=1
    )
    [visual] = align_scenes(scenes, seg)
    assert visual.end_ms <= seg.end_ms + 400


def test_align_until_ends_scene_early() -> None:
    seg = _segment(SPEECH)
    scenes = parse_scenes(
        [
            {
                "type": "stat",
                "value": 10,
                "label": "cheaper",
                "anchor": "Solar power got ten",
                "until": "about the grid.",
            }
        ],
        limit=1,
    )
    [visual] = align_scenes(scenes, seg)
    expected_end = seg.start_ms + _word_ms(SPEECH, "grid.") + PER_WORD - 50 + 400
    assert visual.end_ms == max(expected_end, visual.start_ms + MIN_SCENE_MS)


def test_director_prompt_without_opponent_forbids_rebuttal() -> None:
    brief = TurnBrief(3, "participant_0", "Host", "moderator", "moderator_intro", SPEECH)
    user = build_director_messages(brief, topic="Solar", language="English", budget=1)[1]["content"]
    assert "do not use rebuttal" in user and "This is the host" in user


def test_spoken_numbers_reads_digits_in_many_formats() -> None:
    text = "Prices fell 90% from 2010 to 2020; 1 200 plants, 3,5 млн homes and $4.2 trillion."
    numbers = spoken_numbers(text)
    for expected in (90, 2010, 2020, 1200, 3.5, 4.2):
        assert any(abs(n - expected) < 1e-9 for n in numbers), expected


def _scene(raw: dict[str, object]):
    return TypeAdapter(Scene).validate_python(raw)


def test_grounding_rejects_invented_numbers() -> None:
    speech = "The judge picks Nova: a stronger case on safety and accountability."
    scores = _scene(
        {"type": "bars", "items": [{"label": "Nova", "value": 85}, {"label": "Atlas", "value": 70}]}
    )
    assert not is_grounded(scores, speech)
    assert is_grounded(_scene({"type": "headline", "text": "Safety wins"}), speech)


def test_grounding_accepts_said_scaled_and_small_numbers() -> None:
    speech = (
        "Capacity grew from 140 to 420 gigawatts, a market of $3.4 trillion; one in four homes."
    )
    bars = _scene(
        {
            "type": "bars",
            "items": [{"label": "2014", "value": 140}, {"label": "2024", "value": 420}],
        }
    )
    stat = _scene({"type": "stat", "value": 3_400_000_000_000, "label": "market"})
    ratio = _scene({"type": "proportion", "count": 1, "total": 4, "label": "homes"})
    assert is_grounded(bars, speech) and is_grounded(stat, speech) and is_grounded(ratio, speech)
    interpolated = _scene(
        {
            "type": "line",
            "points": [
                {"label": str(y), "value": v} for y, v in [(1, 140), (2, 200), (3, 290), (4, 420)]
            ],
        }
    )
    assert is_grounded(interpolated, speech)  # half of the values were said
    invented = _scene(
        {
            "type": "line",
            "points": [
                {"label": str(y), "value": v}
                for y, v in [(1, 140), (2, 200), (3, 290), (4, 360), (5, 420)]
            ],
        }
    )
    assert not is_grounded(invented, speech)


def test_parse_scenes_applies_content_rules() -> None:
    payload = {
        "scenes": [
            {"type": "stat", "value": 85, "label": "score"},
            {"type": "quote", "text": "My own words", "author": "Nova"},
            {"type": "quote", "text": "Energy is eternal delight", "author": "William Blake"},
            {"type": "rebuttal", "claim": "X", "response": "Y", "claim_author": "Nova"},
        ]
    }
    kept = parse_scenes(payload, 4, speech=SPEECH, speaker="Nova", opponent="Atlas")
    assert [s.type for s in kept] == ["quote", "rebuttal"]
    assert kept[1].claim_author == "Atlas"  # fixed by code, not trusted from the model
    no_rival = parse_scenes(payload, 4, speech=SPEECH, speaker="Nova", opponent=None)
    assert [s.type for s in no_rival] == ["quote"]


def test_build_briefs_finds_the_last_other_debater() -> None:
    texts = ["intro", "nova one", "atlas one", "host transition", "nova two", "verdict"]
    speakers = [
        "participant_0",
        "participant_1",
        "participant_2",
        "participant_0",
        "participant_1",
        "judge",
    ]
    segs = [
        _segment(t, seq=i).model_copy(update={"speaker_id": sp, "speaker_name": sp})
        for i, (t, sp) in enumerate(zip(texts, speakers, strict=True))
    ]
    roles = {
        "participant_0": "moderator",
        "participant_1": "debater",
        "participant_2": "debater",
        "judge": "judge",
    }
    briefs = build_briefs(segs, roles)
    assert [b.opponent for b in briefs] == [
        None,
        None,
        "participant_1",
        None,
        "participant_2",
        None,
    ]
    assert briefs[4].previous_text == "atlas one"
    assert briefs[5].role == "judge"
    assert briefs[5].debaters == ("participant_1", "participant_2")
    user = build_director_messages(briefs[5], topic="t", language="English", budget=2)[1]
    assert "Debaters: participant_1, participant_2." in user["content"]


def test_diversify_swaps_in_the_spare_to_avoid_repeats() -> None:
    def heads(*kinds: str) -> list[object]:
        raw = {
            "rebuttal": {"type": "rebuttal", "claim": "a", "response": "b"},
            "versus": {
                "type": "versus",
                "left": {"label": "A", "items": ["x"]},
                "right": {"label": "B", "items": ["y"]},
            },
            "headline": {"type": "headline", "text": "Big idea"},
            "bullets": {"type": "bullets", "items": [{"text": "one"}, {"text": "two"}]},
        }
        return [_scene(raw[k]) for k in kinds]

    picked = diversify(
        [
            (1, heads("rebuttal", "versus"), 1),
            (2, heads("rebuttal", "headline"), 1),
            (3, heads("rebuttal", "bullets"), 1),
            (4, heads("headline", "headline", "bullets"), 2),
            (5, heads("versus"), 1),  # no spare: kept as is
        ]
    )
    assert [[s.type for s in picked[i]] for i in range(1, 6)] == [
        ["rebuttal"],
        ["headline"],
        ["bullets"],
        ["headline", "bullets"],
        ["versus"],
    ]


def test_align_starts_with_the_first_element_when_it_comes_late() -> None:
    seg = _segment(SPEECH)
    scenes = parse_scenes(
        [
            {
                "type": "bullets",
                "anchor": "Thank you. Solar power",
                "items": [
                    {"text": "Coal stranded", "anchor": "every new coal plant becomes"},
                    {"text": "Batteries", "anchor": "batteries already balance whole"},
                ],
            }
        ],
        limit=1,
    )
    [visual] = align_scenes(scenes, seg)
    coal = seg.start_ms + _word_ms(SPEECH, "every") - 120
    assert visual.item_ms[0] == coal
    assert visual.start_ms == coal - LEAD_MS
    assert visual.item_ms[1] == seg.start_ms + _word_ms(SPEECH, "batteries") - 120


def test_normalize_countries_reads_codes_names_and_groups() -> None:
    assert normalize_countries("DEU") == ["DEU"]
    assert normalize_countries(["de", "Germany", "united_states", "UK"]) == ["DEU", "USA", "GBR"]
    eu = normalize_countries("EU")
    assert len(eu) == 26 and "FRA" in eu and "MLT" not in eu  # Malta is not on the 110m map
    assert normalize_countries(["Atlantis", 7, None]) == []


def test_new_scene_models_are_lenient() -> None:
    adapter = TypeAdapter(Scene)
    scale = adapter.validate_python(
        {
            "type": "scale",
            "left": {"label": "Costs", "items": [{"text": "Expensive"}, {"text": "Slow"}]},
            "right": {"label": "Benefits", "items": [{"text": "Clean"}] * 5},
            "heavier": "Balanced",
        }
    )
    assert isinstance(scale, ScaleScene) and scale.heavier == "even"
    assert len(scale.right.items) == 3

    matrix = adapter.validate_python(
        {
            "type": "matrix",
            "x_axis": "Cost",
            "y_axis": "Benefit",
            "quadrants": ["a", "b"],  # not four: ignored
            "items": [{"label": "Wind", "x": "low", "y": 85}, {"label": "Coal", "x": 14, "y": -3}],
        }
    )
    assert isinstance(matrix, MatrixScene) and matrix.quadrants == []
    assert [(p.x, p.y) for p in matrix.items] == [(2.5, 8.5), (1.4, 0.0)]

    ranking = adapter.validate_python(
        {
            "type": "ranking",
            "items": [{"label": "China", "value": 30}, {"label": "USA", "value": "n/a"}],
        }
    )
    assert isinstance(ranking, RankingScene) and ranking.layout == "list"
    assert [i.value for i in ranking.items] == [None, None]  # all values or none

    venn = adapter.validate_python({"type": "venn", "sets": [{"label": "A"}, {"label": "B"}]})
    assert isinstance(venn, VennScene) and venn.overlap == ""
    definition = adapter.validate_python({"type": "definition", "term": "UBI", "text": "x" * 400})
    assert isinstance(definition, DefinitionScene) and len(definition.text) == 160


def test_map_scene_keeps_drawable_countries_only() -> None:
    adapter = TypeAdapter(Scene)
    scene = adapter.validate_python(
        {
            "type": "map",
            "regions": [
                {"code": "NOR", "label": "Норвегия", "value": "90%"},
                {"code": "Atlantis", "label": "?"},
                {"codes": ["se", "FIN"], "label": "Nordics", "value": 40},
                {"country": "Germany"},
            ],
        }
    )
    assert isinstance(scene, MapScene)
    assert [r.codes for r in scene.regions] == [["NOR"], ["SWE", "FIN"], ["DEU"]]
    assert [r.value for r in scene.regions] == [None, None, None]  # Germany has no value
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "map", "regions": [{"code": "Atlantis"}]})


def test_director_cannot_design_a_scoreboard() -> None:
    reply = {"scenes": [{"type": "scoreboard", "speaker_ids": ["a", "b"], "winner_id": "a"}]}
    assert parse_scenes(reply, limit=3) == []


def test_parse_scenes_strips_invented_values_from_rankings_and_maps() -> None:
    speech = "China emits the most, then the United States, then India, all with 30 percent."
    reply = {
        "scenes": [
            {
                "type": "pyramid",
                "items": [
                    {"label": "China", "value": 31},
                    {"label": "USA", "value": 14},
                    {"label": "India", "value": 7},
                ],
            },
            {
                "type": "map",
                "regions": [{"code": "CHN", "value": 55}, {"code": "IND", "value": 66}],
            },
        ]
    }
    ranking, world = parse_scenes(reply, limit=3, speech=speech)
    assert isinstance(ranking, RankingScene) and ranking.layout == "pyramid"
    assert [i.value for i in ranking.items] == [None, None, None]
    assert isinstance(world, MapScene) and [r.value for r in world.regions] == [None, None]


def test_director_prompt_lists_new_types_and_how_to_choose() -> None:
    brief = TurnBrief(
        seq_index=9,
        speaker_id="judge",
        speaker_name="Judge",
        role="judge",
        turn_type="verdict",
        text=SPEECH,
    )
    system, user = (
        m["content"]
        for m in build_director_messages(brief, topic="t", language="English", budget=2)
    )
    for kind in ("scale", "matrix", "venn", "ranking", "definition", "map"):
        assert f'"type":"{kind}"' in system
    assert "countries -> map" in system and "alpha-3" in system
    assert "scoreboard" in user  # the judge does not announce the winner itself


COUNTDOWN = (
    "Who pollutes most? In third place India with its coal plants, in second place the United "
    "States with its cars, and in first place China with its huge factories everywhere today."
)


def test_align_ranking_items_in_any_spoken_order() -> None:
    seg = _segment(COUNTDOWN)
    scene = parse_scenes(
        [
            {
                "type": "ranking",
                "anchor": "Who pollutes most",
                "items": [
                    {"label": "China", "anchor": "first place China"},
                    {"label": "USA", "anchor": "second place the United States"},
                    {"label": "India", "anchor": "third place India"},
                ],
            }
        ],
        limit=2,
    )
    [visual] = align_scenes(scene, seg)
    china, usa, india = (t - seg.start_ms for t in visual.item_ms)
    assert india < usa < china  # revealed as counted down, shown in rank order
    assert china >= _word_ms(COUNTDOWN, "first") - LEAD_MS


VERDICT = (
    "Both debaters argued well tonight. Atlas was precise on costs, but after weighing every "
    "argument the winner of this debate is Nova, whose case on storage was never answered."
)


def _verdict_segment(text: str = VERDICT) -> TimelineSegment:
    seg = _segment(text, start_ms=50_000, seq=9)
    return seg.model_copy(update={"speaker_id": "judge", "turn_type": "verdict"})


def test_scoreboard_appears_when_the_winner_is_announced() -> None:
    seg = _verdict_segment()
    board = scoreboard_visual(
        seg, ["participant_0", "participant_1"], winner_id="participant_1", winner_name="Nova"
    )
    assert isinstance(board.scene, ScoreboardScene) and board.anchored
    assert board.start_ms == seg.start_ms + _word_ms(VERDICT, "winner") - LEAD_MS
    assert board.end_ms <= seg.end_ms + 400
    assert board.speaker_id == "judge" and board.scene.winner_id == "participant_1"


def test_scoreboard_without_an_announcement_comes_before_the_end() -> None:
    seg = _verdict_segment(" ".join(["Thoughtful words everywhere."] * 30))
    board = scoreboard_visual(seg, ["a", "b"], winner_id=None, winner_name=None)
    assert not board.anchored
    assert board.end_ms <= seg.end_ms - 2000 and board.end_ms - board.start_ms >= 8000


def _untimed(text: str) -> list[tuple[str, int, int]]:
    return [(w, 0, 0) for w in text.split(" ")]


def test_announcement_index_finds_name_before_or_after_the_win_word() -> None:
    words = _untimed("So Nova wins tonight clearly")
    assert announcement_index(words, "Nova") == 1
    words = _untimed("Победителем становится Nova, поздравляем")
    assert announcement_index(words, "Nova") == 0
    words = _untimed("It ends in a draw tonight")
    assert announcement_index(words, None) == 4
    words = _untimed("Nova argued; nobody wins the lottery")
    assert announcement_index(words, "Atlas") is None


def test_make_room_cuts_moves_or_drops_overlapping_scenes() -> None:
    def visual(vid: str, start: int, end: int) -> TimelineVisual:
        scene = HeadlineScene(type="headline", text="x")
        return TimelineVisual(
            id=vid,
            seq_index=9,
            speaker_id="judge",
            start_ms=start,
            end_ms=end,
            scene=scene,
            item_ms=[start, end - 100],
        )

    pinned = visual("board", 10_000, 19_000)
    before = visual("before", 2_000, 12_000)  # cut to end at 10 s
    inside = visual("inside", 11_000, 18_000)  # dropped
    after = visual("after", 17_000, 26_000)  # moved to start at 19 s
    short = visual("short", 9_000, 21_000)  # 1 s before, 2 s after: dropped
    out = make_room([before, inside, after, short], pinned)
    assert [(v.id, v.start_ms, v.end_ms) for v in out] == [
        ("before", 2_000, 10_000),
        ("board", 10_000, 19_000),
        ("after", 19_000, 26_000),
    ]
    assert all(v.start_ms <= t <= v.end_ms for v in out for t in v.item_ms)


def test_sides_named_after_debaters_get_the_exact_names() -> None:
    debaters = ("Debater 1", "Debater 2", "Nova")
    assert debater_label("Debater One", debaters) == "Debater 1"
    assert debater_label("debater two", debaters) == "Debater 2"
    assert debater_label("NOVA", debaters) == "Nova"
    assert debater_label("Benefits", debaters) == "Benefits"
    reply = {
        "scenes": [
            {
                "type": "versus",
                "left": {"label": "Debater One", "items": ["Data"]},
                "right": {"label": "Debater Two", "items": ["Risks"]},
            }
        ]
    }
    [scene] = parse_scenes(reply, limit=2, debaters=debaters)
    assert (scene.left.label, scene.right.label) == ("Debater 1", "Debater 2")


def test_director_prompt_carries_hints_sketches_and_pictures() -> None:
    brief = TurnBrief(
        seq_index=3,
        speaker_id="participant_1",
        speaker_name="Nova",
        role="debater",
        turn_type="opening",
        text=SPEECH,
        hints=(("bar chart - Denmark 50%, Germany 30%", "the grid"),),
        images=True,
    )
    system, user = (
        m["content"]
        for m in build_director_messages(brief, topic="T", language="English", budget=2)
    )
    assert '"type":"sketch"' in system and '"type":"image"' in system
    assert "a real place or thing worth seeing -> image" in system
    assert '1. bar chart - Denmark 50%, Germany 30% (right after: "the grid")' in user
    plain = replace(brief, hints=(), images=False)
    system, user = (
        m["content"]
        for m in build_director_messages(plain, topic="T", language="English", budget=2)
    )
    assert '"type":"image"' not in system and '"type":"sketch"' in system
    assert "asked the studio" not in user


def test_scene_budget_counts_hints() -> None:
    short = " ".join(["word"] * 20)  # ~8 s
    assert scene_budget(short, "debater") == 0
    assert scene_budget(short, "debater", hints=2) == 1
    long = " ".join(["word"] * 100)  # ~38 s -> 2 scenes
    assert scene_budget(long, "debater", hints=3) == 3


def test_parse_scenes_keeps_one_picture_and_respects_the_switch() -> None:
    payload = {
        "scenes": [
            {"type": "photo", "subject": "wind farm", "anchor": "x"},
            {"type": "image", "subject": "coal plant", "anchor": "y"},
            {"type": "drawing", "subject": "a piggy bank", "anchor": "z"},
        ]
    }
    kinds = [s.type for s in parse_scenes(payload, 5)]
    assert kinds == ["image", "sketch"]
    assert [s.type for s in parse_scenes(payload, 5, images=False)] == ["sketch"]


def test_hint_numbers_count_as_said() -> None:
    hinted = {"scenes": [{"type": "stat", "value": 73, "suffix": "%", "label": "x", "anchor": "a"}]}
    assert parse_scenes(hinted, 2, speech=SPEECH) == []
    assert len(parse_scenes(hinted, 2, speech=f"{SPEECH} chart: 73%")) == 1


def test_keys_are_stable_and_survive_filled_fields() -> None:
    from app.schemas.visuals import ImageScene, assign_keys, key_seq, scene_key

    scene = ImageScene.model_validate({"type": "image", "subject": "wind farm", "anchor": "x"})
    key = scene_key(4, scene)
    filled = scene.model_copy(update={"src": "visuals/0123456789abcdef.webp", "kind": "photo"})
    assert scene_key(4, filled) == key and key_seq(key) == 4
    assert [s.key for s in assign_keys(4, [scene])] == [key]


def test_scene_summaries_and_checkable_types() -> None:
    from app.services.media.visuals import is_checkable, is_disputable, scene_summary

    bars = _scene(
        {
            "type": "bars",
            "title": "Wind",
            "unit": "%",
            "items": [{"label": "Denmark", "value": 50}, {"label": "Germany", "value": 30.5}],
        }
    )
    assert scene_summary(bars) == 'bars "Wind": Denmark 50%, Germany 30.5%'
    quote = _scene({"type": "quote", "text": "To be", "author": "Hamlet"})
    assert scene_summary(quote) == 'quote: "To be" — Hamlet'
    headline = _scene({"type": "headline", "text": "Go big"})
    definition = _scene({"type": "definition", "term": "UBI", "text": "Money for all"})
    assert is_checkable(bars) and is_checkable(quote)
    assert not is_checkable(headline) and not is_checkable(definition)
    assert is_disputable(definition) and not is_disputable(headline)
    ranking = _scene({"type": "ranking", "items": [{"label": "A"}, {"label": "B"}]})
    assert not is_checkable(ranking) and is_disputable(ranking)


def test_timeline_visual_carries_check_and_disputes() -> None:
    visual = TimelineVisual.model_validate(
        {
            "id": "v1_0",
            "seq_index": 1,
            "speaker_id": "participant_1",
            "start_ms": 0,
            "end_ms": 5000,
            "key": "1:abc",
            "check": {"verdict": "disputed", "note": "n", "sources": [{"url": "https://a.org"}]},
            "disputes": [
                {"by_id": "participant_2", "by_name": "Rex", "seq_index": 4, "reason": "r"}
            ],
            "scene": {"type": "stat", "value": 1, "label": "x"},
        }
    )
    assert visual.check is not None and visual.check.sources[0].title == ""
    assert visual.disputes[0].by_name == "Rex"


def test_tiny_charts_from_requests_are_rescued() -> None:
    speech = "Public transport use rose by over 30 percent, sales went from 10 to 12 percent."
    payload = {
        "scenes": [
            {
                "type": "bar_chart",
                "anchor": "rose by over 30 percent",
                "title": "Transit use",
                "unit": "%",
                "items": [{"label": "Copenhagen", "value": 30}],
            },
            {
                "type": "line",
                "anchor": "sales went",
                "points": [{"label": "before", "value": 10}, {"label": "after", "value": 12}],
            },
        ]
    }
    stat, bars = parse_scenes(payload, 3, speech=speech)
    assert isinstance(stat, StatScene) and stat.value == 30 and stat.suffix == "%"
    assert stat.label == "Transit use" and stat.anchor == "rose by over 30 percent"
    assert isinstance(bars, BarsScene) and [i.value for i in bars.items] == [10, 12]
