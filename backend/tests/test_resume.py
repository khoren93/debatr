from decimal import Decimal

from app.models.models import Turn
from app.services.credits import charge_due, run_ref
from app.services.resume import answered, discarded, resume_point


def _turn(seq: int, text: str = "An answer.", error: str | None = None, cost: float = 0.0) -> Turn:
    return Turn(seq_index=seq, text=text, error=error, usage_json={"cost": cost})


def test_answered_needs_text_and_no_error():
    assert answered(_turn(0))
    assert not answered(_turn(0, text="  "))
    assert not answered(_turn(0, text="Half a sen", error="provider died"))
    assert not answered(_turn(0, text="[Error: HTTP 500]"))  # rows from before turn.error


def test_resume_point_is_the_first_failed_or_missing_turn():
    assert resume_point([]) == 0
    assert resume_point([_turn(0), _turn(1), _turn(2, error="HTTP 429")]) == 2
    assert resume_point([_turn(0), _turn(1)]) == 2  # the job crashed before saving turn 2
    assert resume_point([_turn(1), _turn(0, text="")]) == 0  # order does not matter


def test_discarded_drops_the_failed_turn_and_keeps_its_cost():
    turns = [_turn(0, cost=0.01), _turn(1, cost=0.02), _turn(2, error="died", cost=0.003)]
    dropped, cost = discarded(turns, 2)
    assert [t.seq_index for t in dropped] == [2]
    assert cost == 0.003
    assert discarded(turns, 3) == ([], 0.0)


def test_a_resumed_run_is_charged_only_for_what_it_added():
    assert charge_due(Decimal("1.5"), Decimal("0")) == Decimal("1.5")
    assert charge_due(Decimal("1.5"), Decimal("1.2")) == Decimal("0.3")
    assert charge_due(Decimal("1.0"), Decimal("1.2")) == Decimal("0")  # never a refund


def test_run_refs_keep_the_first_charge_as_before():
    assert run_ref("debate:x:llm", 0) == "debate:x:llm"
    assert run_ref("debate:x:llm", 1) == "debate:x:llm:2"
    assert run_ref("debate:x:llm", 2) == "debate:x:llm:3"
