"""AI covers (services/media/cover.py): the director's input, parsing, the prompt, the check,
versions and who gets one. Nothing here calls a model or draws a picture."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.models.models import CreditTransaction, Debate, DebateParticipant, Turn
from app.schemas.schemas import DebateConfig
from app.services.api_tokens import pending_estimate, with_token_defaults
from app.services.credits import cover_charge_usd
from app.services.ledger import category
from app.services.media import cover, cover_logos
from app.services.media.cover import (
    Brief,
    Rival,
    add_version,
    auto_cover,
    build_prompt,
    cover_expected,
    current_version,
    episode_brief,
    fit_hook,
    free_run_of,
    parse_brief,
    parse_check,
    queued_state,
    references,
    remove_version,
    rivals_of,
    select_version,
)
from app.services.media.cover_logos import Logo
from app.services.openrouter_client import OpenRouterClient

CLAUDE = Logo(name="claude-color", description="an orange starburst", png=b"png-claude")
GEMINI = Logo(name="gemini-color", description="a four-pointed star", png=b"png-gemini")
NVIDIA = Logo(name="nvidia-color", description="the green NVIDIA eye", png=b"png-nvidia")


def base_config(**extra: Any) -> DebateConfig:
    participants = [{"role": "debater", "model_id": "m", "display_name": "A"}]
    return DebateConfig.model_validate(
        {"topic": "Cats or dogs?", "participants": participants, **extra}
    )


def rival(name: str, logo: Logo | None, color: str = "#6C9CFF", side: str | None = None) -> Rival:
    return Rival(name=name, model=f"x/{name.lower()}", side=side, color=color, logo=logo)


def brief(rivals: int = 2, hook: str = "WHO OWNS IT?") -> Brief:
    return Brief(
        hook=hook,
        concept="Two robots tug a giant game cartridge.",
        setting="A neon arcade.",
        rivals=[f"Rival {i} grins and points." for i in range(rivals)],
        centerpiece="A giant game cartridge.",
    )


def turn(seq: int, name: str, text: str, kind: str = "opening", error: str | None = None) -> Turn:
    return Turn(
        seq_index=seq, round_id="round_1", turn_type=kind, speaker_name=name, text=text, error=error
    )


# --- the director's input --------------------------------------------------------------------


def test_the_director_never_reads_the_verdict():
    conf = {"format": "rap_battle", "topic": "Own your games?", "language": "English"}
    turns = [
        turn(0, "The MC", "Welcome!", "moderator_intro"),
        turn(1, "Claude", "I own my bars."),
        turn(2, "Gemini", "", error="429"),
        turn(3, "⚖️ Verdict", "Winner: Claude. Gemini stumbled.", "verdict"),
    ]
    text = episode_brief(
        conf, [rival("Claude", CLAUDE), rival("Gemini", None, side="against")], turns
    )
    assert "rap battle" in text and "Topic: Own your games?" in text
    assert "logo: an orange starburst" in text and "no logo: invent a glowing emblem" in text
    assert "argues against it" in text
    assert "I own my bars." in text
    assert "Winner" not in text and "stumbled" not in text and "429" not in text


def test_long_episodes_are_cut_per_turn():
    turns = [turn(i, "A", "word " * 2000) for i in range(4)]
    text = episode_brief({"topic": "T"}, [rival("A", None)], turns)
    assert len(text) < cover.BRIEF_TEXT_CHARS + 1500


def test_rivals_follow_the_site():
    debate = Debate(
        config_json={
            "participants": [
                {"role": "moderator"},
                {"role": "debater", "side": "for"},
                {"role": "debater"},
            ]
        },
        participants=[
            DebateParticipant(role="moderator", model_id="x/host", persona_name="The Host"),
            DebateParticipant(role="debater", model_id="anthropic/claude-x", persona_name="Claude"),
            DebateParticipant(role="debater", model_id="google/gemini-y", persona_name=None),
        ],
    )
    out = rivals_of(debate, logos=False)
    assert [(r.name, r.side, r.color) for r in out] == [
        ("Claude", "for", "#6C9CFF"),
        ("gemini-y", None, "#FF7A66"),
    ]


# --- the brief ---------------------------------------------------------------------------------


def test_fit_hook_keeps_it_short_and_loud():
    assert fit_hook("who owns it?") == "WHO OWNS IT?"
    assert fit_hook("one two three four five") == "ONE TWO THREE FOUR"
    assert fit_hook("extraordinarily long words everywhere") == "EXTRAORDINARILY LONG"
    assert len(fit_hook("A" * 40)) == cover.HOOK_MAX_CHARS
    assert fit_hook("дом или офис?") == "ДОМ ИЛИ ОФИС?"
    assert fit_hook('  "  ') == ""


def test_parse_brief_checks_the_answer():
    answer = {
        "hook": "Who owns it?",
        "concept": "c",
        "setting": "s",
        "rivals": ["a", "b"],
        "centerpiece": "p",
    }
    parsed = parse_brief(f"```json\n{json.dumps(answer)}\n```", 2)
    assert parsed.hook == "WHO OWNS IT?" and parsed.rivals == ["a", "b"]
    with pytest.raises(ValueError, match="describes 2 rivals, not 3"):
        parse_brief(json.dumps(answer), 3)
    with pytest.raises(ValueError, match="misses a field"):
        parse_brief(json.dumps({**answer, "setting": " "}), 2)
    with pytest.raises(ValueError):
        parse_brief("no json at all", 2)


# --- the prompt --------------------------------------------------------------------------------


def test_two_rivals_face_off_with_their_logos():
    rivals = [rival("Claude", CLAUDE), rival("Gemini", GEMINI, "#FF7A66")]
    prompt = build_prompt(brief(), rivals, {"format": "debate", "language": "English"})
    assert "face off from the left and right thirds" in prompt
    assert '"WHO OWNS IT?" is the headline:' in prompt  # Latin: no script note
    assert "reference image 1 (an orange starburst)" in prompt
    assert "reference image 2 (a four-pointed star)" in prompt
    assert '"CLAUDE" in bold under the left rival in cool blue' in prompt
    assert '"GEMINI" in bold under the right rival in warm coral' in prompt
    assert 'a glowing "VS" between them' in prompt and '"AI DEBATE"' in prompt
    assert "8% at the top and at the bottom may be cropped" in prompt
    assert "suggests a winner" in prompt and "same logo" not in prompt


def test_four_rivals_in_a_row_one_logo_shared_one_missing():
    rivals = [
        rival("Free Router A", NVIDIA),
        rival("Free Router B", NVIDIA, "#FF7A66"),
        rival("Claude", CLAUDE, "#A78BFA"),
        rival("Acme", None, "#34D399"),
    ]
    prompt = build_prompt(brief(4), rivals, {"format": "debate"})
    assert "four rivals stand in a row" in prompt
    assert prompt.count("reference image 1 (the green NVIDIA eye)") == 2
    assert "reference image 2 (an orange starburst)" in prompt
    assert "glowing abstract symbol in mint green" in prompt
    assert "Several rivals carry the same logo" in prompt
    assert '"FREE ROUTER A" in bold under the far left rival' in prompt
    assert 'glowing "VS" marks between neighbours' in prompt
    assert [logo.name for logo in references(rivals)] == ["nvidia-color", "claude-color"]


def test_other_scripts_are_copied_exactly():
    prompt = build_prompt(
        brief(hook="ДОМ ИЛИ ОФИС?"),
        [rival("A", None), rival("B", None)],
        {"language": "Russian", "format": "rap_battle"},
    )
    assert "in Russian (copy every character exactly as given" in prompt
    assert '"RAP BATTLE"' in prompt and "concert lighting" in prompt


# --- the check ---------------------------------------------------------------------------------


def test_parse_check():
    assert parse_check('{"ok": true, "problems": []}') == (True, [])
    assert parse_check('{"ok": false, "problems": ["hook misspelled"]}') == (
        False,
        ["hook misspelled"],
    )
    assert parse_check('{"problems": ["extra text"]}') == (False, ["extra text"])
    assert parse_check("I cannot see the image") == (True, ["unreadable check"])


# --- versions ----------------------------------------------------------------------------------


def version(vid: str) -> dict[str, Any]:
    return {
        "id": vid,
        "files": {
            "full": f"{vid}.webp",
            "small": f"{vid}-768.webp",
            "yt": f"{vid}-yt.jpg",
            "og": f"{vid}-og.jpg",
        },
    }


def test_versions_keep_the_newest_five_and_show_the_new_one():
    state: dict[str, Any] = {}
    dropped: list[dict[str, Any]] = []
    for i in range(7):
        state, removed = add_version(state, version(f"v{i}"))
        dropped += removed
    assert [v["id"] for v in cover.versions(state)] == ["v2", "v3", "v4", "v5", "v6"]
    assert [v["id"] for v in dropped] == ["v0", "v1"]
    assert current_version(state)["id"] == "v6"  # type: ignore[index]


def test_select_and_remove_versions():
    state, _ = add_version({}, version("a"))
    state, _ = add_version(state, version("b"))
    state = select_version(state, "a")
    assert current_version(state)["id"] == "a"  # type: ignore[index]
    assert current_version(select_version(state, None)) is None  # the markup cover
    with pytest.raises(KeyError):
        select_version(state, "zzz")
    state, removed = remove_version(state, "a")
    assert removed["id"] == "a" and state["current"] == "b"
    state, _ = remove_version(state, "b")
    assert state["current"] is None and cover.versions(state) == []
    assert cover.version_files(version("x")) == ["x.webp", "x-768.webp", "x-yt.jpg", "x-og.jpg"]


def test_queued_state_records_who_pays():
    state = queued_state(
        {"current": "a", "error": "old"},
        source="owner",
        own_key=False,
        free=False,
        prices={"markup": 1.2},
        hook="mine now",
    )
    assert state["current"] == "a" and state["error"] is None
    assert state["request"]["hook"] == "MINE NOW" and state["request"]["prices"] == {"markup": 1.2}


# --- who gets one ------------------------------------------------------------------------------


def conf(**billing: Any) -> dict[str, Any]:
    return {"participants": [{"model_id": "openai/gpt-5"}], "billing": billing}


def test_auto_cover_rules():
    paid = conf(own_key=False, free_run=False)
    free = conf(own_key=False, free_run=True)
    args = {"moderation": "approved", "is_public": True, "balance": 1.0}
    assert auto_cover(paid, mode="paid", **args) == "paid"
    assert auto_cover(conf(own_key=True), mode="paid", **{**args, "balance": 0.0}) == "own"
    assert auto_cover(paid, mode="paid", **{**args, "balance": 0.0}) is None  # nothing to pay with
    assert auto_cover(free, mode="paid", **args) is None
    assert auto_cover(free, mode="all_public", **args) == "free"
    assert auto_cover(free, mode="all_public", **{**args, "is_public": False}) is None
    assert auto_cover(paid, mode="off", **args) is None
    assert auto_cover({**paid, "cover": False}, mode="paid", **args) is None
    assert auto_cover(paid, mode="paid", **{**args, "moderation": "flagged"}) is None
    assert auto_cover(paid, mode="paid", **{**args, "moderation": "rejected"}) is None
    # Flagged only because the check could not run: the cover is drawn, the debate stays private.
    flagged = {**args, "moderation": "flagged", "moderation_source": "fallback"}
    assert auto_cover(paid, mode="paid", **flagged) == "paid"
    assert auto_cover(paid, mode="paid", **{**args, "moderation": "none"}) == "paid"


def test_free_runs_from_before_the_flag_are_told_by_their_models():
    assert free_run_of({"participants": [{"model_id": "x/y:free"}], "billing": {"own_key": False}})
    assert not free_run_of({"participants": [{"model_id": "openai/gpt-5"}], "billing": {}})
    assert not free_run_of(
        {"participants": [{"model_id": "x/y:free"}], "billing": {"own_key": True}}
    )


def test_estimates_and_tokens():
    assert cover_expected(None, "paid", free_run=False)
    assert not cover_expected(None, "paid", free_run=True)
    assert not cover_expected(False, "all_public", free_run=False)
    assert not cover_expected(True, "off", free_run=False)
    assert cover_charge_usd(0.035, 1.2) == Decimal("0.042")
    # API tokens get no paid cover unless they ask for one.
    assert with_token_defaults(base_config()).cover is False
    assert with_token_defaults(base_config(cover=True)).cover is True
    billing = {
        "billing": {"estimate_usd": 0.4, "media_estimate_usd": 0.1, "cover_estimate_usd": 0.04}
    }
    assert pending_estimate("completed", "none", billing, "queued") == Decimal("0.04")
    assert pending_estimate("completed", "running", billing, "running") == Decimal("0.14")


def test_ledger_tells_covers_apart():
    tx = CreditTransaction(
        amount_usd=Decimal("-0.04"),
        kind="media",
        description="AI cover: Topic",
        provider_ref="debate:x:cover:abc",
    )
    assert category(tx) == "cover"
    assert (
        category(
            CreditTransaction(
                amount_usd=Decimal("-0.04"), kind="media", description="AI cover: Topic"
            )
        )
        == "cover"
    )


# --- providers -----------------------------------------------------------------------------------


async def test_generate_image_sends_references_quality_and_the_key():
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"b64_json": "aW1n"}], "usage": {"cost": 0.02}})

    client = OpenRouterClient(transport=httpx.MockTransport(handler))
    body = await client.generate_image(
        "openai/gpt-image",
        "a cover",
        resolution=None,
        quality="medium",
        references=["data:image/png;base64,AA"],
        api_key="own-key",
    )
    assert body["usage"]["cost"] == 0.02
    assert seen["auth"] == "Bearer own-key"
    assert seen["body"] == {
        "model": "openai/gpt-image",
        "prompt": "a cover",
        "aspect_ratio": "16:9",
        "quality": "medium",
        "input_references": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}
        ],
    }


def test_fetch_logo_asks_the_site(monkeypatch: pytest.MonkeyPatch):
    def get(url: str, params: dict[str, str], timeout: float) -> httpx.Response:
        assert url.endswith("/og/logo.png") and params == {"model": "anthropic/claude-x"}
        return httpx.Response(200, content=b"png", headers={"x-logo": "claude-color"})

    monkeypatch.setattr(cover_logos.httpx, "get", get)
    logo = cover_logos.fetch_logo("anthropic/claude-x")
    assert logo == Logo(
        name="claude-color", description=cover_logos.DESCRIPTIONS["claude-color"], png=b"png"
    )
    monkeypatch.setattr(cover_logos.httpx, "get", lambda *a, **k: httpx.Response(404))
    assert cover_logos.fetch_logo("acme/x") is None
    assert cover_logos.fetch_logo(None) is None


def test_every_logo_of_the_site_is_described():
    icons = Path(__file__).resolve().parents[2] / "frontend" / "public" / "model-icons"
    if not icons.is_dir():
        pytest.skip("the frontend is not next to the backend")
    names = sorted(p.stem for p in icons.glob("*.svg"))
    assert [n for n in names if n not in cover_logos.DESCRIPTIONS] == []


# --- the build, with every provider faked --------------------------------------------------------


@pytest.fixture
def studio(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Fakes for draw_cover: the director's answer, pictures and the check's verdicts."""
    seen: dict[str, Any] = {"images": [], "checks": ['{"ok": true, "problems": []}']}
    brief_answer = {
        "hook": "Who owns it?",
        "concept": "c",
        "setting": "s",
        "rivals": ["a", "b"],
        "centerpiece": "p",
    }

    def direct(model: str, messages: list[dict[str, Any]], **kwargs: Any):
        seen["director"] = messages[1]["content"]
        return json.dumps(brief_answer), [], {"cost": 0.007}

    def image(model: str, prompt: str, **kwargs: Any):
        seen["images"].append(kwargs)
        seen["prompt"] = prompt
        return b"picture", {"cost": 0.02}

    def check(model: str, messages: list[dict[str, Any]], **kwargs: Any):
        return seen["checks"].pop(0) if len(seen["checks"]) > 1 else seen["checks"][0], {
            "cost": 0.001
        }

    monkeypatch.setattr(cover, "complete_message", direct)
    monkeypatch.setattr(cover, "generate_image", image)
    monkeypatch.setattr(cover, "complete", check)
    monkeypatch.setattr(cover.ffmpeg, "fill_jpeg", lambda src, dst, **kw: dst.write_bytes(b"jpeg"))
    monkeypatch.setattr(
        cover, "fetch_logo", lambda model: CLAUDE if model and "claude" in model else None
    )
    seen["work"] = tmp_path
    return seen


def finished_debate() -> Debate:
    return Debate(
        config_json={
            "topic": "Own your games?",
            "participants": [{"role": "debater"}, {"role": "debater"}],
        },
        participants=[
            DebateParticipant(role="debater", model_id="anthropic/claude-x", persona_name="Claude"),
            DebateParticipant(role="debater", model_id="acme/y", persona_name="Acme"),
        ],
        turns=[
            turn(0, "Claude", "Mine."),
            turn(1, "Acme", "Rented."),
            turn(2, "Judge", "Winner: Claude", "verdict"),
        ],
    )


def test_draw_cover_bills_the_director_and_the_picture(studio: dict[str, Any]):
    drawn = cover.draw_cover(finished_debate(), hook=None, api_key="own", work=studio["work"])
    assert drawn.image == b"picture" and drawn.tries == 1 and drawn.brief.hook == "WHO OWNS IT?"
    assert drawn.billed_usd == pytest.approx(0.027) and drawn.check_usd == pytest.approx(0.001)
    assert "Winner" not in studio["director"]
    sent = studio["images"][0]
    assert sent["api_key"] == "own" and sent["references"] == [
        f"data:image/png;base64,{'cG5nLWNsYXVkZQ=='}"
    ]
    assert "glowing abstract symbol" in studio["prompt"]  # Acme has no logo


def test_draw_cover_tries_once_more_then_gives_up(studio: dict[str, Any]):
    studio["checks"] = [
        '{"ok": false, "problems": ["hook misspelled"]}',
        '{"ok": true, "problems": []}',
    ]
    drawn = cover.draw_cover(finished_debate(), hook="mine", api_key=None, work=studio["work"])
    assert drawn.tries == 2 and drawn.brief.hook == "MINE"
    assert drawn.billed_usd == pytest.approx(0.047)  # both pictures are paid
    studio["checks"] = ['{"ok": false, "problems": ["extra text"]}']
    with pytest.raises(cover.CoverError, match="failed its check twice"):
        cover.draw_cover(finished_debate(), hook=None, api_key=None, work=studio["work"])
