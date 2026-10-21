"""Commands end to end against the fake server (typer's CliRunner: not a terminal, so every
prompt takes its non-interactive path)."""

import json

import httpx
import pytest
from conftest import (
    DEBATE_ID,
    FINAL_TURNS,
    FORMATS,
    LIVE_EVENTS,
    SITE,
    TOKEN,
    FakeServer,
    battle_detail,
    detail,
    free_estimate,
    turn,
)
from rich.console import Console
from typer.testing import CliRunner

from debatr import cli, render
from debatr.config import Login, Store

runner = CliRunner()


@pytest.fixture
def app(server: FakeServer, monkeypatch):
    monkeypatch.setattr(cli, "DebatrClient", server.client_factory())
    monkeypatch.setenv("COLUMNS", "120")

    def invoke(*args: str, input: str | None = None, token: str | None = TOKEN):
        env = {"DEBATR_TOKEN": token} if token else {}
        return runner.invoke(cli.app, ["--url", SITE, *args], input=input, env=env)

    return invoke


def live_debate(server: FakeServer) -> None:
    server.on("POST /debates/estimate", free_estimate())
    server.on("POST /debates", {"debate_id": DEBATE_ID, "status": "queued", "message": "ok"})
    # run: after create, follow: first look, on "connected", after the stream.
    server.on(
        f"GET /debates/{DEBATE_ID}",
        [detail("queued"), detail("running"), detail("running"), detail("completed")],
    )
    server.on(f"GET /debates/{DEBATE_ID}/stream", LIVE_EVENTS)


def test_run_streams_the_debate(app, server):
    live_debate(server)
    result = app("run", "Cats or dogs?", "-d", "acme/alpha", "-d", "acme/beta")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Welcome! Nova, please begin." in out
    assert "Cats are independent." in out and "[vis" not in out and "a cat alone" not in out
    assert out.count("Dogs are loyal.") == 1  # streamed once, never repeated
    assert "Winner: Nova" in out
    assert "Completed" in out
    body = json.loads(server.calls("POST /debates")[0].content)
    assert body["auto_publish"] is False
    assert [p["model_id"] for p in body["participants"]] == [
        "openrouter/free",
        "acme/alpha",
        "acme/beta",
    ]


def test_run_json(app, server):
    live_debate(server)
    result = app("run", "Cats or dogs?", "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["id"] == DEBATE_ID and data["status"] == "completed"
    assert data["verdict"]["winner"] == "Nova"
    assert len(data["turns"]) == 4


def test_run_detach(app, server):
    live_debate(server)
    result = app("run", "Cats or dogs?", "--detach")
    assert result.exit_code == 0
    assert result.stdout.strip() == DEBATE_ID
    assert not server.calls(f"GET /debates/{DEBATE_ID}/stream")


def test_paid_runs_need_consent_without_a_terminal(app, server):
    live_debate(server)
    server.on("POST /debates/estimate", free_estimate(credits_cost_usd=0.42))
    result = app("run", "Q?")
    assert result.exit_code == 1 and "pass --yes" in result.output
    assert not server.calls("POST /debates")

    result = app("run", "Q?", "--max-cost", "0.1")
    assert result.exit_code == 1 and "above --max-cost" in result.output

    result = app("run", "Q?", "--yes", "--detach")
    assert result.exit_code == 0 and server.calls("POST /debates")


def test_token_budget_and_credits_are_explained(app, server):
    server.on(
        "POST /debates/estimate",
        free_estimate(credits_cost_usd=2.0, token_budget_usd=0.5, sufficient=False),
    )
    result = app("run", "Q?", "--yes")
    assert result.exit_code == 1 and "may spend only $0.50 more" in result.output
    server.on(
        "POST /debates/estimate",
        free_estimate(credits_cost_usd=9.0, credits_before=1.0, sufficient=False),
    )
    result = app("run", "Q?", "--yes")
    assert result.exit_code == 1 and "Not enough credits" in result.output


def test_print_config_hides_keys(app, monkeypatch):
    monkeypatch.setenv("DEBATR_OPENROUTER_KEY", "sk-or-secret")
    result = app("run", "Q?", "--print-config", token=None)
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["user_provider_key"] == "***"
    assert "sk-or-secret" not in result.output


def test_run_with_a_config_file(app, server, tmp_path):
    live_debate(server)
    path = tmp_path / "debate.json"
    path.write_text(
        json.dumps(
            {
                "topic": "Old",
                "participants": [{"role": "debater", "model_id": "m", "display_name": "A"}],
            }
        )
    )
    result = app("run", "New topic?", "--config", str(path), "--detach")
    assert result.exit_code == 0, result.output
    body = json.loads(server.calls("POST /debates")[0].content)
    assert body["topic"] == "New topic?" and body["auto_publish"] is False


def test_needs_a_login(app):
    result = app("run", "Q?", token=None)
    assert result.exit_code == 1 and "Not signed in" in result.output


def test_login_with_token_whoami_logout(app, server):
    server.on("GET /auth/me", {"email": "a@b.co", "display_name": "A", "credits_usd": 4.5})
    server.on(
        "GET /auth/tokens/current",
        {
            "name": "laptop",
            "token_hint": "debatr_…tttt",
            "spend_limit_usd": 5,
            "spent_usd": 1.25,
            "expires_at": None,
        },
    )
    server.on("DELETE /auth/tokens/current", httpx.Response(204))

    result = app("login", "--with-token", input=f"{TOKEN}\n", token=None)
    assert result.exit_code == 0, result.output
    login = Store.load().logins[SITE]
    assert login == Login(token=TOKEN, email="a@b.co", token_name="laptop")

    result = app("whoami", token=None)
    assert result.exit_code == 0
    assert "$4.50" in result.output and "spent $1.25 of $5.00" in result.output

    result = app("logout", token=None)
    assert result.exit_code == 0
    assert server.calls("DELETE /auth/tokens/current")
    assert SITE not in Store.load().logins


def test_device_login(app, server, monkeypatch):
    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(cli.asyncio, "sleep", no_wait)
    server.on(
        "POST /auth/device",
        {
            "device_code": "secret",
            "user_code": "WDJB-MJHT",
            "verification_uri": f"{SITE}/device",
            "verification_uri_complete": f"{SITE}/device?code=WDJB-MJHT",
            "expires_in": 600,
            "interval": 3,
        },
    )
    server.on(
        "POST /auth/device/token", [{"status": "pending"}, {"status": "approved", "token": TOKEN}]
    )
    server.on("GET /auth/me", {"email": "a@b.co"})
    server.on("GET /auth/tokens/current", {"name": "Debatr CLI on box"})
    result = app("login", "--no-browser", token=None)
    assert result.exit_code == 0, result.output
    assert "WDJB-MJHT" in result.output and f"{SITE}/device?code=WDJB-MJHT" in result.output
    assert Store.load().logins[SITE].token == TOKEN
    assert json.loads(server.calls("POST /auth/device")[0].content)["client_name"].startswith(
        "Debatr CLI on "
    )


def test_device_login_denied(app, server, monkeypatch):
    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(cli.asyncio, "sleep", no_wait)
    server.on(
        "POST /auth/device",
        {
            "device_code": "s",
            "user_code": "WDJB-MJHT",
            "verification_uri": "u",
            "expires_in": 600,
            "interval": 3,
        },
    )
    server.on("POST /auth/device/token", {"status": "denied"})
    result = app("login", "--no-browser", token=None)
    assert result.exit_code == 1 and "denied" in result.output
    assert Store.load().logins == {}


def test_show_formats(app, server, tmp_path):
    server.on(f"GET /debates/{DEBATE_ID}", detail("completed"))
    text = app("show", DEBATE_ID)
    assert (
        text.exit_code == 0
        and "Winner: Nova" in text.output
        and "Cats are independent." in text.output
    )

    md = app("show", f"{SITE}/debate/{DEBATE_ID}", "--format", "markdown")
    assert md.stdout.startswith("# Cats or dogs?")

    as_json = app("show", DEBATE_ID, "-f", "json")
    assert json.loads(as_json.stdout)["verdict"]["winner"] == "Nova"

    path = tmp_path / "debate.md"
    saved = app("show", DEBATE_ID, "-o", str(path))
    assert saved.exit_code == 0 and path.read_text().startswith("# Cats or dogs?")


def test_show_public_slug(app, server):
    server.on(
        "GET /gallery/k3m9xq2p7w",
        detail("completed", share_url=f"{SITE}/d/k3m9xq2p7w", is_public=True),
    )
    result = app("show", f"{SITE}/d/k3m9xq2p7w", "-f", "json", token=None)
    assert result.exit_code == 0
    assert json.loads(result.stdout)["url"] == f"{SITE}/d/k3m9xq2p7w"


def test_list_models_gallery_leaderboard(app, server):
    rows = [
        {
            "id": DEBATE_ID,
            "topic": "Cats or dogs?",
            "status": "completed",
            "verdict": {"winner_name": "Nova"},
            "created_at": "2026-10-17T10:00:00Z",
        }
    ]
    server.on("GET /debates", [rows])  # one response whose body is a list
    assert "Cats or dogs?" in app("list").output

    server.on(
        "GET /models",
        {
            "data": [
                {
                    "id": "acme/old",
                    "name": "Old",
                    "is_free": True,
                    "created": 1,
                    "pricing": {"prompt": "0", "completion": "0"},
                    "context_length": 8000,
                },
                {
                    "id": "acme/new",
                    "name": "New",
                    "is_free": False,
                    "created": 2,
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                    "context_length": 200000,
                },
            ]
        },
    )
    listed = app("models", "--json", token=None)
    assert [m["id"] for m in json.loads(listed.stdout)] == ["acme/new", "acme/old"]
    free = app("models", "--free", "--json", token=None)
    assert [m["id"] for m in json.loads(free.stdout)] == ["acme/old"]
    table = app("models", "acme", token=None)
    assert "3.00" in table.output and "15.00" in table.output

    server.on(
        "GET /gallery",
        {
            "items": [
                {
                    "slug": "k3m9xq2p7w",
                    "topic": "Tabs or spaces?",
                    "participants": [],
                    "likes": 3,
                    "votes": 1,
                }
            ],
            "total": 1,
        },
    )
    assert "Tabs or spaces?" in app("gallery", token=None).output
    assert server.calls("GET /gallery")[0].url.params["sort"] == "trending"

    server.on(
        "GET /gallery/leaderboard",
        {
            "entries": [
                {
                    "model_id": "acme/new",
                    "rating": 1042,
                    "debates": 3,
                    "votes": 9,
                    "is_free": False,
                },
                {
                    "model_id": "acme/quiet",
                    "rating": 1000,
                    "rated": False,
                    "debates": 1,
                    "votes": 0,
                    "is_free": True,
                },
            ],
            "total_votes": 9,
            "total_debates": 4,
        },
    )
    board = app("leaderboard", token=None).output
    assert "1042" in board  # no `rated` field (older servers) counts as rated
    assert "no votes" in board and "1000" not in board


def test_delete_needs_yes_without_a_terminal(app, server):
    server.on(f"DELETE /debates/{DEBATE_ID}", httpx.Response(204))
    assert app("delete", DEBATE_ID).exit_code == 1
    assert not server.calls(f"DELETE /debates/{DEBATE_ID}")
    assert app("delete", DEBATE_ID, "--yes").exit_code == 0
    assert server.calls(f"DELETE /debates/{DEBATE_ID}")


def test_audio_download(app, server, tmp_path):
    server.on(f"GET /debates/{DEBATE_ID}", detail("completed"))
    server.on(
        f"GET /debates/{DEBATE_ID}/media",
        {
            "media_status": "ready",
            "urls": {"full_mp3": f"/api/media/files/{DEBATE_ID}/full.mp3?v=1"},
        },
    )
    server.on(f"GET /media/files/{DEBATE_ID}/full.mp3", httpx.Response(200, content=b"ID3"))
    dest = tmp_path / "talk.mp3"
    result = app("audio", DEBATE_ID, "-o", str(dest))
    assert result.exit_code == 0, result.output
    assert dest.read_bytes() == b"ID3"


def test_audio_missing_explains_build(app, server):
    server.on(f"GET /debates/{DEBATE_ID}", detail("completed"))
    server.on(f"GET /debates/{DEBATE_ID}/media", {"media_status": "none", "progress": {}})
    result = app("audio", DEBATE_ID)
    assert result.exit_code == 1 and "--build" in result.output


def test_api_errors_are_one_line(app, server):
    server.on(
        f"POST /debates/{DEBATE_ID}/stop",
        httpx.Response(409, json={"detail": "Debate is already completed"}),
    )
    result = app("stop", DEBATE_ID)
    assert result.exit_code == 1
    assert "Error: Debate is already completed" in result.output
    assert "Traceback" not in result.output


def test_version():
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0 and result.output.startswith("debatr ")


def test_run_reconnects_when_the_stream_drops(app, server, monkeypatch):
    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(cli.asyncio, "sleep", no_wait)
    live_debate(server)
    server.on(
        f"GET /debates/{DEBATE_ID}",
        [
            detail("queued"),
            detail("running"),
            detail("running"),
            detail("running"),
            detail("running"),
            detail("completed"),
        ],
    )
    server.on(
        f"GET /debates/{DEBATE_ID}/stream",
        [httpx.Response(502, text="bad gateway"), b": ping\n\n", LIVE_EVENTS],
    )
    result = app("run", "Cats or dogs?")
    assert result.exit_code == 0, result.output
    assert len(server.calls(f"GET /debates/{DEBATE_ID}/stream")) == 3
    assert result.output.count("Cats are independent.") == 1
    assert "Winner: Nova" in result.output


FAILED_TURNS = [
    FINAL_TURNS[0],
    turn(1, "participant_1", "Nova", "", error="HTTP 429: rate limited"),
]


def failed_debate(server: FakeServer, **estimate) -> None:
    failed = detail(
        "error",
        turns=FAILED_TURNS,
        error_message="Nova (acme/alpha) could not answer: HTTP 429: rate limited",
        is_owner=True,
    )
    server.on(f"POST /debates/{DEBATE_ID}/resume/estimate", free_estimate(from_turn=1, **estimate))
    server.on(f"POST /debates/{DEBATE_ID}/resume", {"debate_id": DEBATE_ID, "status": "queued"})
    # resume: after the call, follow: first look, on "connected", after the stream.
    server.on(
        f"GET /debates/{DEBATE_ID}",
        [failed, detail("queued"), detail("running"), detail("running"), detail("completed")],
    )
    server.on(f"GET /debates/{DEBATE_ID}/stream", LIVE_EVENTS)


def test_a_failed_run_points_to_resume(app, server):
    failed_debate(server)
    server.on(
        f"GET /debates/{DEBATE_ID}",
        detail(
            "error",
            turns=FAILED_TURNS,
            error_message="Nova (acme/alpha) could not answer: HTTP 429: rate limited",
            is_owner=True,
        ),
    )
    result = app("watch", DEBATE_ID)
    assert result.exit_code == 1
    assert "could not answer: HTTP 429" in result.output
    assert f"debatr resume {DEBATE_ID}" in result.output


def test_resume_follows_the_debate_to_the_end(app, server, monkeypatch):
    monkeypatch.setenv("DEBATR_OPENROUTER_KEY", "sk-or-own")
    failed_debate(server)
    server.on(
        f"GET /debates/{DEBATE_ID}",
        [detail("queued"), detail("running"), detail("running"), detail("completed")],
    )
    result = app("resume", DEBATE_ID)
    assert result.exit_code == 0, result.output
    assert "Resumed from turn 2" in result.output
    assert "Winner: Nova" in result.output and "Completed" in result.output
    for route in (
        f"POST /debates/{DEBATE_ID}/resume/estimate",
        f"POST /debates/{DEBATE_ID}/resume",
    ):
        assert json.loads(server.calls(route)[0].content) == {"user_provider_key": "sk-or-own"}


def test_paid_resume_needs_consent_and_respects_max_cost(app, server):
    failed_debate(server, credits_cost_usd=0.3)
    result = app("resume", DEBATE_ID)
    assert result.exit_code == 1 and "pass --yes" in result.output
    result = app("resume", DEBATE_ID, "--max-cost", "0.1")
    assert result.exit_code == 1 and "above --max-cost" in result.output
    assert not server.calls(f"POST /debates/{DEBATE_ID}/resume")

    result = app("resume", DEBATE_ID, "--yes", "--detach")
    assert result.exit_code == 0 and DEBATE_ID in result.stdout
    assert len(server.calls(f"POST /debates/{DEBATE_ID}/resume")) == 1


def test_resume_explains_why_not(app, server):
    server.on(
        f"POST /debates/{DEBATE_ID}/resume/estimate",
        httpx.Response(409, json={"detail": "Only a debate that failed can be resumed"}),
    )
    result = app("resume", DEBATE_ID)
    assert result.exit_code == 1
    assert "Error: Only a debate that failed can be resumed" in result.output


def test_a_rap_battle_from_the_terminal(app, server):
    server.on("GET /formats", [FORMATS])  # one response: the list
    server.on("POST /debates/estimate", free_estimate(credits_cost_usd=0.9, music_ms=150_000))
    server.on("POST /debates", {"debate_id": DEBATE_ID, "status": "queued", "message": "ok"})
    server.on(f"GET /debates/{DEBATE_ID}", battle_detail("queued"))
    args = ["run", "Tabs or spaces?", "--format", "rap_battle", "--audio", "--detach", "--yes"]
    result = app(*args, "--flow", "smooth", "--flow", "sharp")
    assert result.exit_code == 0, result.output
    console = Console(record=True, width=100)
    console.print(render.estimate_table(free_estimate(credits_cost_usd=0.9, music_ms=150_000)))
    assert "~2m 30s of beat and verses" in console.export_text()
    body = json.loads(server.calls("POST /debates")[0].content)
    assert body["format"] == "rap_battle" and body["media_plan"]["provider"] == "elevenlabs"
    assert body["media_plan"]["flows"] == {"participant_1": "smooth", "participant_2": "sharp"}

    # A typo would fall back to the default flow on the server: refused here, nothing started.
    typo = app(*args, "--flow", "smoth")
    assert typo.exit_code == 1 and "Unknown flow smoth: pick from gritty, sharp, smooth" in (
        typo.output
    )
    assert len(server.calls("POST /debates")) == 1
    too_many = app("run", "Q?", "--format", "rap_battle", "-d", "a/b", "-d", "a/c", "-d", "a/d")
    assert too_many.exit_code == 1 and "exactly two rappers" in too_many.output


def test_formats_gallery_and_leaderboard_by_format(app, server):
    server.on("GET /formats", [FORMATS])  # one response: the list
    listed = app("formats", token=None)
    assert listed.exit_code == 0, listed.output
    assert "rap_battle" in listed.output and "gritty" in listed.output
    assert "(default)" in listed.output and "premium voices only" in listed.output

    server.on(
        "GET /gallery", {"items": [{"slug": "abcd1234", "topic": "Q?", "format": "rap_battle"}]}
    )
    shown = app("gallery", "--format", "rap_battle", token=None)
    assert "RAP BATTLE" in shown.output
    assert server.calls("GET /gallery")[0].url.params["format"] == "rap_battle"

    server.on("GET /gallery/leaderboard", {"entries": [], "total_votes": 0})
    app("leaderboard", token=None)
    app("leaderboard", "--format", "rap_battle", token=None)
    asked = [r.url.params.get("format") for r in server.calls("GET /gallery/leaderboard")]
    assert asked == [None, "rap_battle"]


def test_a_battle_without_its_track_explains_the_build(app, server):
    server.on(f"GET /debates/{DEBATE_ID}", battle_detail())
    server.on(f"GET /debates/{DEBATE_ID}/media", {"media_status": "none"})
    missing = app("audio", DEBATE_ID)
    assert missing.exit_code == 1 and "ElevenLabs, paid" in missing.output
    edge = app("audio", DEBATE_ID, "--build", "--voices", "edge")
    assert edge.exit_code == 1 and "premium voices only" in edge.output


def _covered(status: str, **extra: object) -> dict:
    current = {
        "id": "v1",
        "url": f"/api/media/files/{DEBATE_ID}/covers/v1.webp",
        "yt_url": f"/api/media/files/{DEBATE_ID}/covers/v1-yt.jpg",
        "hook": "WHO WINS?",
    }
    cover = {
        "status": status,
        "current": current if status == "ready" else None,
        "price_usd": 0.042,
        "reason": None,
        **extra,
    }
    return detail("completed", cover=cover)


def test_cover_waits_and_saves_the_thumbnail(app, server, monkeypatch, tmp_path):
    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(cli.asyncio, "sleep", no_wait)
    server.on(
        f"GET /debates/{DEBATE_ID}", [_covered("none"), _covered("running"), _covered("ready")]
    )
    server.on(f"POST /debates/{DEBATE_ID}/cover", {"status": "queued"})
    server.on(
        f"GET /media/files/{DEBATE_ID}/covers/v1-yt.jpg", httpx.Response(200, content=b"JPEG")
    )
    dest = tmp_path / "thumb.jpg"
    result = app("cover", DEBATE_ID, "--hook", "Who wins?", "-o", str(dest), "-y")
    assert result.exit_code == 0, result.output
    assert json.loads(server.calls(f"POST /debates/{DEBATE_ID}/cover")[0].content) == {
        "hook": "Who wins?"
    }
    assert dest.read_bytes() == b"JPEG"
    assert f"{SITE}/api/media/files/{DEBATE_ID}/covers/v1.webp" in result.output


def test_cover_explains_why_not(app, server):
    server.on(f"GET /debates/{DEBATE_ID}", _covered("none", reason="not_finished"))
    result = app("cover", DEBATE_ID)
    assert result.exit_code == 1 and "not finished" in result.output
    result = app("cover", DEBATE_ID, "--hook", "x" * 30)
    assert result.exit_code == 1 and "1 to 22 characters" in result.output


def test_run_asks_for_a_cover(app, server):
    result = app("run", "Cats or dogs?", "--cover", "--print-config")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["cover"] is True
    result = app("run", "Cats or dogs?", "--print-config")
    assert "cover" not in json.loads(result.output)


def test_gallery_by_language(app, server):
    server.on(
        "GET /gallery",
        {"items": [{"slug": "abcd1234", "topic": "Лучше ли офис?", "language_code": "ru"}]},
    )
    shown = app("gallery", "--language", "RU", token=None)
    assert shown.exit_code == 0, shown.output
    assert server.calls("GET /gallery")[0].url.params["language"] == "ru"
    # Every language unless asked: installed CLIs keep their old answer.
    app("gallery", token=None)
    assert "language" not in server.calls("GET /gallery")[1].url.params
    wrong = app("gallery", "--language", "russian", token=None)
    assert wrong.exit_code != 0 and "two-letter" in wrong.output
