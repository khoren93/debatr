"""Finance and model statistics of the admin console (`/api/admin/finance*`, `/api/admin/models`).

Finance needs `money` (the CSV also sudo, audited); Models needs `debates.read` and shows the
cost per turn only with `money`. Reads run in a read-only transaction; Stripe is asked for the
period's checkout sessions only when it is configured (in a thread pool, at most MAX_SESSIONS).
"""

import logging
import time
from typing import Any

import stripe
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.admin.access import AdminContext, read_only_db, require_admin, sudo_required
from app.core.config import settings
from app.core.db import get_db
from app.models.models import ProviderUsage, utcnow
from app.schemas.admin import FinanceOut, FinancePeriod, ModelsOut, ModelsPeriod
from app.services import runtime_settings
from app.services.admin import audit, finance
from app.services.ledger import slug
from app.services.openrouter_client import openrouter_client

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_SESSIONS = 1000


def _stripe_sessions(since: int) -> list[dict[str, Any]]:
    """Checkout sessions created since `since` (unix time), newest first."""
    client = stripe.StripeClient(settings.STRIPE_SECRET_KEY or "")
    page = client.v1.checkout.sessions.list(params={"created": {"gte": since}, "limit": 100})
    out: list[dict[str, Any]] = []
    for session in page.auto_paging_iter():
        details = session.customer_details
        out.append(
            {
                "id": session.id,
                "payment_status": session.payment_status,
                "amount_total": session.amount_total,
                "customer_email": session.customer_email or (details.email if details else None),
                "created": session.created,
            }
        )
        if len(out) >= MAX_SESSIONS:
            break
    return out


async def _reconcile(db: AsyncSession, start: Any, end: Any) -> dict[str, Any]:
    if not settings.STRIPE_SECRET_KEY:
        return {"configured": False}
    credited = await finance.stripe_topups(db, start, end)
    try:
        sessions = await run_in_threadpool(_stripe_sessions, int(start.timestamp()))
    except stripe.StripeError as exc:
        logger.warning("Stripe reconciliation failed: %s", exc)
        return {"configured": True, "error": str(exc)[:300]}
    in_period = [s for s in sessions if int(s.get("created") or 0) < int(end.timestamp())]
    return {"configured": True, **finance.reconcile(in_period, credited)}


async def build_finance(db: AsyncSession, period: FinancePeriod) -> dict[str, Any]:
    now = utcnow()
    start, end, bucket = finance.finance_window(period, now, await finance.first_activity(db))
    series, totals, by_purpose = await finance.money_series(db, start, end, bucket)
    tracked = await db.scalar(select(func.min(ProviderUsage.created_at)))
    return {
        "period": period,
        "bucket": bucket,
        "start": start,
        "end": end,
        "totals": totals.out(),
        "series": series,
        "cost_by_purpose": by_purpose,
        "cost_tracked_since": tracked,
        **await finance.balances_now(db),
        "top_payers": await finance.top_accounts(db, start, end, kinds=("topup",), sign=1),
        "top_spenders": await finance.top_accounts(
            db, start, end, kinds=("debate", "media"), sign=-1
        ),
        "stripe": await _reconcile(db, start, end),
    }


@router.get("/finance", response_model=FinanceOut)
async def finance_page(
    period: FinancePeriod = "30d",
    _ctx: AdminContext = Depends(require_admin("money")),
    db: AsyncSession = Depends(read_only_db),
) -> FinanceOut:
    return FinanceOut.model_validate(await build_finance(db, period))


@router.post("/finance/export")
async def finance_export(
    request: Request,
    period: FinancePeriod = "30d",
    ctx: AdminContext = Depends(require_admin("money")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The period's series as CSV (sudo; written to the audit log)."""
    if not ctx.session.is_sudo(time.time()):
        raise sudo_required()
    now = utcnow()
    start, end, bucket = finance.finance_window(period, now, await finance.first_activity(db))
    series, _totals, _by_purpose = await finance.money_series(db, start, end, bucket)
    await audit.record(
        db,
        "finance.exported",
        request=request,
        actor=ctx.user,
        target_type="finance",
        after={"period": period, "bucket": bucket, "rows": len(series)},
    )
    name = f"{slug(settings.PROJECT_NAME)}-finance-{period}-{now:%Y%m%d}.csv"
    return Response(
        finance.finance_csv(series),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/models", response_model=ModelsOut)
async def models_page(
    period: ModelsPeriod = "30d",
    ctx: AdminContext = Depends(require_admin("debates.read")),
    db: AsyncSession = Depends(read_only_db),
) -> ModelsOut:
    span = finance.MODEL_PERIODS[period]
    since = utcnow() - span if span is not None else None
    usage = await finance.usage_by_model(db, since)
    debates = await finance.debate_facts(db, since)
    catalogue = {m["id"]: m for m in await openrouter_client.get_models()}
    rows = finance.model_rows(
        usage,
        debates,
        catalogue,
        with_money=ctx.can("money"),
        turned_off=(await runtime_settings.current()).disabled_models,
    )
    return ModelsOut.model_validate({"period": period, "rows": rows})
