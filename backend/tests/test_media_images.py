from app.services.media.images import (
    Candidate,
    ai_prompt,
    build_pick_messages,
    commons_params,
    image_digest,
    parse_commons,
    parse_pick,
    photo_credit,
    search_queries,
    strip_html,
)


def _page(index: int, title: str, **info):
    base = {
        "mime": "image/jpeg",
        "thumburl": f"https://upload.wikimedia.org/thumb/{index}.jpg",
        "thumbwidth": 1600,
        "thumbheight": 1000,
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{index}.jpg",
        "extmetadata": {
            "LicenseShortName": {"value": "CC BY-SA 4.0"},
            "Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:Ann">Ann</a> &amp; Bo'},
        },
    }
    base.update(info)
    return {"index": index, "title": f"File:{title}", "imageinfo": [base]}


def test_parse_commons_keeps_free_landscape_photos_in_rank_order():
    payload = {
        "query": {
            "pages": {
                "a": _page(3, "Wind farm 3.jpg"),
                "b": _page(1, "Wind farm 1.jpg"),
                "c": _page(2, "Logo of a wind company.jpg"),
                "d": _page(
                    4, "NC.jpg", extmetadata={"LicenseShortName": {"value": "CC BY-NC 2.0"}}
                ),
                "e": _page(5, "Small.jpg", thumbwidth=300, thumbheight=200),
                "f": _page(6, "Tall.jpg", thumbwidth=800, thumbheight=1600),
                "g": _page(7, "Gif.gif", mime="image/gif"),
                "h": _page(8, "Evil.jpg", thumburl="https://evil.example/x.jpg"),
                "i": _page(
                    9, "PD.jpg", extmetadata={"LicenseShortName": {"value": "Public domain"}}
                ),
            }
        }
    }
    found = parse_commons(payload)
    assert [c.title for c in found] == [
        "File:Wind farm 1.jpg",
        "File:Wind farm 3.jpg",
        "File:PD.jpg",
    ]
    assert found[0].author == "Ann & Bo"
    assert found[2].author == "Unknown author"
    assert photo_credit(found[0]) == "Photo: Ann & Bo · CC BY-SA 4.0 · Wikimedia Commons"
    assert parse_commons({}) == [] and parse_commons(None) == []


def test_pick_parsing_and_prompts():
    assert parse_pick('{"pick": 2, "reason": "clear"}', 3) == 1
    assert parse_pick('{"pick": null}', 3) is None
    assert parse_pick('{"pick": 5}', 3) is None
    assert parse_pick('{"pick": true}', 3) is None
    assert parse_pick("nope", 3) is None
    messages = build_pick_messages("wind farm", [b"\xff\xd8a", b"\xff\xd8b"])
    content = messages[0]["content"]
    assert "wind farm" in content[0]["text"] and "2 numbered pictures" in content[0]["text"]
    assert content[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert len([c for c in content if c["type"] == "image_url"]) == 2
    assert "No text" in ai_prompt("A coal plant.") and ai_prompt("A coal plant.").startswith(
        "A coal plant. "
    )


def test_helpers():
    assert strip_html("<b>Photo</b> by&nbsp;<i>X</i>") == "Photo by X"
    assert image_digest("photo", "Wind  Farm") == image_digest("photo", "wind farm")
    assert image_digest("ai", "wind farm") != image_digest("photo", "wind farm")
    assert commons_params("wind farm")["gsrsearch"] == "wind farm filetype:bitmap"
    assert Candidate("u", "p", "t", "a", "l", 1, 1).license == "l"


def test_search_retries_with_fewer_words():
    assert search_queries("Pontevedra old town pedestrian street, Spain") == [
        "Pontevedra old town pedestrian street Spain",
        "Pontevedra old town pedestrian",
        "Pontevedra old",
    ]
    assert search_queries("wind farm") == ["wind farm"]
