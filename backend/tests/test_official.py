"""The brand's name is the official account's alone (services/official)."""

import pytest

from app.api.routes_auth import default_name
from app.services.official import reserved_name


@pytest.mark.parametrize(
    "name",
    [
        "Debatr",
        "DEBATR",
        "debatr",
        " Debatr ",
        "Debatr Team",
        "d.e.b.a.t.r",
        "The_Debatr",
        "D\u0435batr",
    ],
)
def test_brand_names_are_reserved(name: str) -> None:
    # The last one has a Cyrillic "e" (U+0435).
    assert reserved_name(name)


def test_the_russian_spelling_is_reserved() -> None:
    assert reserved_name("\u0414\u0435\u0431\u0430\u0442\u0440")  # Дебатр


@pytest.mark.parametrize("name", ["Debater", "Khoren", "Debate fan", "Bat Ray", ""])
def test_other_names_are_free(name: str) -> None:
    assert not reserved_name(name)


def testdefault_name_never_takes_the_brand() -> None:
    assert default_name("debatr@example.com") == "Debater"
    assert default_name("jane.doe@example.com") == "Jane Doe"
