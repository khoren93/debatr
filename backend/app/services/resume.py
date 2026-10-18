"""Failed turns stop a debate, and the owner can resume it from there.

A debate that goes on after a speaker failed has the others argue against silence (and the
judge score it), so the worker stops at the first turn without an answer (`status=error`).
`POST /api/debates/{id}/resume` drops that turn (and anything after it), keeps the turns before
it and the participants' models (a Free Router keeps its pinned model), and queues the run from
that turn with fresh keys; the estimate and the charge cover only what the new run adds
(`estimate_debate(from_turn=…)`, `credits.charge_debate_sync`).
"""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Debate, Turn


def answered(turn: Turn) -> bool:
    """Whether a saved turn holds a real answer (old rows kept errors inline as "[Error …")."""
    text = (turn.text or "").strip()
    return bool(text) and not turn.error and not text.startswith("[Error")


def resume_point(turns: Sequence[Turn]) -> int:
    """Index of the first turn to run again: the first failed or missing one (a crashed job
    saves nothing). Equal to the number of scheduled turns when only the verdict is left."""
    by_seq = {t.seq_index: t for t in turns}
    index = 0
    while index in by_seq and answered(by_seq[index]):
        index += 1
    return index


def discarded(turns: Sequence[Turn], from_seq: int) -> tuple[list[Turn], float]:
    """Turns a resume drops and what they cost (a stream that died midway may have billed
    tokens; the cost stays in the debate's totals, `discarded_cost`, so it is not lost)."""
    dropped = [t for t in turns if t.seq_index >= from_seq]
    cost = sum(float((t.usage_json or {}).get("cost") or 0.0) for t in dropped)
    return dropped, round(cost, 6)


async def reset_for_resume(db: AsyncSession, debate: Debate, from_seq: int) -> None:
    """Drop the failed turn and everything after it (their cost joins `discarded_cost`) and put
    the debate back in the queue state; the caller sets the config, commits and enqueues."""
    dropped, cost = discarded(debate.turns, from_seq)
    for turn in dropped:
        await db.delete(turn)
    totals = dict(debate.totals_json or {})
    if cost:
        totals["discarded_cost"] = round(float(totals.get("discarded_cost") or 0) + cost, 6)
    debate.totals_json = totals
    if debate.media_status != "none":
        debate.media_status = "none"  # the audio lacks the new turns; the TTS cache stays
    debate.status = "queued"
    debate.error_message = None
    debate.ended_at = None
