import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.scheduler import TRENDING_TICK_SECONDS, build_scheduler
from app.services import trending
from app.services.media import llm
from app.services.trending import (
    Headline,
    TopicDraft,
    TrendingError,
    balanced_pool,
    blocked_term,
    build_batch,
    build_review_messages,
    build_topic_messages,
    drop_same_story,
    is_due,
    normalize_category,
    parse_feed,
    parse_review,
    parse_topics,
    pool_size,
    rank_topics,
    save_batch,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test</title>
<item><title>EU delays the AI Act &amp; its fines</title><link>https://example.com/ai-act</link>
  <description><![CDATA[<p>Brussels pushes back <b>rules</b>.</p>]]></description>
  <pubDate>Sat, 17 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>Old story</title><link>https://example.com/old</link>
  <pubDate>Mon, 12 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>Script link</title><link>javascript:alert(1)</link>
  <pubDate>Sat, 17 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>Undated story</title><link>https://example.com/undated</link></item>
</channel></rss>"""

GOOGLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Google News</title>
<item><title>Fed holds rates steady - Reuters</title><link>https://news.google.com/a/1</link>
  <description>&lt;ol&gt;&lt;li&gt;links&lt;/li&gt;&lt;/ol&gt;</description>
  <source url="https://www.reuters.com">Reuters</source>
  <pubDate>Sat, 17 Oct 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""


def _headline(title: str, outlet: str = "BBC", n: int = 0) -> Headline:
    return Headline(outlet=outlet, title=title, summary="", url=f"https://example.com/{n}")


def _topic(question: str, heat: int, outlets: list[str]) -> TopicDraft:
    sources = [_headline(question, o, i) for i, o in enumerate(outlets)]
    return TopicDraft("Label", question, "Brief.", "tech", heat, sources)


# --- feeds ---------------------------------------------------------------------------------


def test_parse_feed_keeps_fresh_safe_links_and_cleans_text() -> None:
    items = parse_feed(RSS, "BBC", now=NOW)
    assert [i.title for i in items] == ["EU delays the AI Act & its fines", "Undated story"]
    first = items[0]
    assert first.summary == "Brussels pushes back rules ."
    assert first.url == "https://example.com/ai-act"
    assert first.published_at == datetime(2026, 10, 17, 8, 0, tzinfo=UTC)
    assert first.source()["outlet"] == "BBC"
    assert items[1].published_at is None


def test_parse_feed_names_the_real_outlet_of_google_news_items() -> None:
    [item] = parse_feed(GOOGLE_RSS, "Google News", now=NOW)
    assert item.outlet == "Reuters"
    assert item.title == "Fed holds rates steady"
    assert item.summary == ""


def test_balanced_pool_round_robin_without_repeats() -> None:
    a = [_headline("A1"), _headline("A2"), _headline("A3")]
    b = [_headline("B1"), _headline("a1!")]  # same title as A1 after normalising
    pool = balanced_pool([a, b, []], limit=4)
    assert [h.title for h in pool] == ["A1", "B1", "A2", "A3"]
    assert balanced_pool([a, b], limit=2) == [a[0], b[0]]


def test_pool_size_bounds() -> None:
    assert pool_size(5) == 60
    assert pool_size(50) == 150
    assert pool_size(500) == 400


# --- safety --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Government to ban porn depicting strangulation",
        "Pornographic deepfakes spread",
        "Sexual abuse inquiry opens",
        "Man raped woman, court hears",
        "Apple pulls nudify apps",
        "Three killed in attack",
        "Stabbing at a train station",
        "Terrorist cell arrested",
        "Rise in teen suicide rates",
        "Graphic footage shows the scene",
        "Grooming gangs report published",
    ],
)
def test_blocklist_catches_sexual_and_violent_stories(text: str) -> None:
    assert blocked_term(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "Rapeseed prices climb",
        "Al Gore launches climate fund",
        "Is sexism still a problem in tech?",
        "Sussex council raises taxes",
        "Should we have an AI kill switch?",
        "Should abortion be legal?",
        "Pedometer apps boost walking",
    ],
)
def test_blocklist_leaves_ordinary_stories(text: str) -> None:
    assert blocked_term(text) is None


def test_prompts_carry_the_safety_rules() -> None:
    pool = [_headline("EU delays the AI Act")]
    topic_prompt = build_topic_messages(pool, 1, today="Saturday")[1]["content"]
    assert "[1] BBC · recent · EU delays the AI Act" in topic_prompt
    assert "sexual content of any kind" in topic_prompt
    review = build_review_messages([_topic("Should AI be regulated?", 5, ["BBC"])])
    assert "[1] Label | Should AI be regulated? | Brief." in review[1]["content"]
    assert "sexual content of any kind" in review[1]["content"]


# --- model replies -------------------------------------------------------------------------


def _reply(topics: list[dict[str, Any]]) -> str:
    return "```json\n" + json.dumps({"topics": topics}) + "\n```"


def test_parse_topics_grounds_normalises_and_drops() -> None:
    pool = [_headline("AI Act", "BBC", 1), _headline("AI Act fines", "DW", 2)]
    text = _reply(
        [
            {
                "label": "AI Act",
                "question": "Should the EU delay its AI rules?",
                "brief": "The EU delayed the AI Act.",
                "category": "Technology",
                "heat": 12,
                "sources": [1, "2", 2, 9],
            },
            {"label": "Ghost", "question": "Should we ban invented stories?", "sources": []},
            {"label": "Bad", "question": "Should porn sites verify ages?", "sources": [1]},
            {"label": "Again", "question": "Should the EU delay its AI rules?", "sources": [2]},
            {"label": "Short", "question": "Why?", "sources": [1]},
        ]
    )
    topics, dropped = parse_topics(text, pool)
    assert len(topics) == 1
    topic = topics[0]
    assert topic.category == "tech"
    assert topic.heat == 10
    assert topic.sources == pool
    assert topic.outlets == 2
    assert [d["reason"] for d in dropped] == [
        "no source headline",
        "blocked term: porn",
        "duplicate",
    ]


def test_parse_topics_salvages_a_cut_off_reply() -> None:
    pool = [_headline("AI Act")]
    full = json.dumps(
        {
            "topics": [
                {"label": "A", "question": "Should the EU delay its AI rules?", "sources": [1]},
                {"label": "B", "question": "Should cities ban cars?", "sources": [1]},
            ]
        }
    )
    cut = full[: full.index('"Should cities')]
    topics, _ = parse_topics(cut, pool)
    assert [t.label for t in topics] == ["A"]


def test_parse_topics_rejects_garbage() -> None:
    with pytest.raises(TrendingError):
        parse_topics("sorry, no news today", [])
    with pytest.raises(TrendingError):
        parse_topics('{"items": []}', [])


def test_normalize_category() -> None:
    assert normalize_category("Politics") == "politics"
    assert normalize_category("environment") == "science"
    assert normalize_category("law") == "politics"
    assert normalize_category("something odd") == "world"
    assert normalize_category(None) == "world"


def test_rank_topics_rewards_stories_many_outlets_carry() -> None:
    lone = _topic("Should A?", 8, ["BBC"])
    wide = _topic("Should B?", 6, ["BBC", "DW", "NPR"])  # 6 + 2 * 1.5 = 9
    tie = _topic("Should C?", 8, ["NPR"])
    assert rank_topics([lone, wide, tie]) == [wide, lone, tie]


def test_drop_same_story_keeps_the_best_ranked_telling() -> None:
    shared = _headline("Pope leaves hospital", "BBC", 7)
    best = TopicDraft(
        "Pope", "Should the Vatican publish health records?", "", "world", 8, [shared]
    )
    again = TopicDraft("Pope 2", "Should popes retire?", "", "world", 5, [_headline("x"), shared])
    other = _topic("Should cities ban cars?", 4, ["DW"])
    kept, dropped = drop_same_story([best, again, other])
    assert kept == [best, other]
    assert dropped == [
        {
            "question": "Should popes retire?",
            "reason": "same story as: Should the Vatican publish health records?",
        }
    ]


def test_parse_review() -> None:
    reply = '{"reject": [{"id": 2, "reason": "gore"}, {"id": 9}, {"id": "1"}]}'
    assert parse_review(reply, 3) == {1: "gore", 0: "rejected by the review"}
    assert parse_review('{"reject": []}', 3) == {}
    with pytest.raises(TrendingError):
        parse_review("I cannot help with that", 3)


# --- the whole batch -----------------------------------------------------------------------


def _fake_llm(replies: list[str]) -> Any:
    calls: list[list[dict[str, Any]]] = []

    def complete_message(model: str, messages: list[dict[str, Any]], **_: Any) -> Any:
        calls.append(messages)
        return replies[len(calls) - 1], [], {"cost": 0.01}

    complete_message.calls = calls  # type: ignore[attr-defined]
    return complete_message


def test_build_batch_filters_headlines_and_applies_the_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = [
        [_headline("EU delays the AI Act", "BBC", 1), _headline("Porn ban vote", "BBC", 2)],
        [_headline("Cities weigh car bans", "DW", 3)],
        [],  # a failed feed
    ]
    monkeypatch.setattr(trending, "fetch_feeds", lambda: groups)
    topics = _reply(
        [
            {"label": "AI Act", "question": "Should the EU delay AI rules?", "sources": [1]},
            {"label": "Cars", "question": "Should cities ban cars?", "sources": [2], "heat": 9},
        ]
    )
    fake = _fake_llm([topics, '{"reject": [{"id": 2, "reason": "too local"}]}'])
    monkeypatch.setattr(llm, "complete_message", fake)

    result = build_batch("test/model", topic_count=5)

    prompt = fake.calls[0][1]["content"]
    assert "Porn ban vote" not in prompt  # blocked before the model saw it
    assert "[2] DW · recent · Cities weigh car bans" in prompt
    # The cars topic ranked first (heat 9), so the review's id 2 is the AI Act topic.
    assert [t.question for t in result.topics] == ["Should cities ban cars?"]
    assert result.cost_usd == pytest.approx(0.02)
    assert result.stats["feeds_ok"] == 2
    assert result.stats["headlines_blocked"] == 1
    assert result.stats["blocked"] == [{"title": "Porn ban vote", "term": "porn"}]
    assert result.stats["dropped"] == [
        {"question": "Should the EU delay AI rules?", "reason": "too local"}
    ]

    batch = save_batch(Session(), result)  # unbound: add() needs no database
    assert batch.topic_count == 1
    assert [(t.rank, t.category, t.outlets) for t in batch.topics] == [(1, "world", 1)]
    assert batch.topics[0].sources_json[0]["url"] == "https://example.com/3"


def test_build_batch_fails_closed_without_a_review(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trending, "fetch_feeds", lambda: [[_headline("EU delays the AI Act")]])
    topics = _reply([{"label": "AI", "question": "Should the EU delay AI rules?", "sources": [1]}])
    monkeypatch.setattr(llm, "complete_message", _fake_llm([topics, "I'd rather not."]))
    with pytest.raises(TrendingError):
        build_batch("test/model", topic_count=5)


def test_build_batch_without_feeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trending, "fetch_feeds", lambda: [[], []])
    with pytest.raises(TrendingError, match="every feed failed"):
        build_batch("test/model", topic_count=5)


# --- scheduling ----------------------------------------------------------------------------


def test_is_due() -> None:
    assert is_due(None, NOW, 24)
    assert not is_due(None, NOW, 0)  # automatic refreshes off
    assert not is_due(NOW - timedelta(hours=10), NOW, 24)
    # An hourly tick a few minutes early still builds the daily batch.
    assert is_due(NOW - timedelta(hours=23, minutes=55), NOW, 24)
    assert not is_due(NOW - timedelta(days=20), NOW, 720)
    assert is_due(NOW - timedelta(days=30), NOW, 720)


def test_scheduler_registers_the_hourly_trending_check() -> None:
    cron = build_scheduler(None)  # type: ignore[arg-type]  # registering needs no Redis
    trending, recovery = cron.get_jobs()
    assert trending.func_name == "app.services.trending.refresh_trending_job"
    assert trending.interval == TRENDING_TICK_SECONDS
    assert trending.queue_name == "background"  # turns never wait behind it
    assert recovery.func_name == "app.services.recovery.recover_runs_job"
    assert recovery.interval == 60 and recovery.queue_name == "background"
