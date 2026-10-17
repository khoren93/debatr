from app.worker import parse_queue_names


def test_parse_queue_names() -> None:
    assert parse_queue_names("default, media") == ["default", "media"]
    assert parse_queue_names("") == ["default", "background", "media"]  # settings default
    assert parse_queue_names(None) == ["default", "background", "media"]
