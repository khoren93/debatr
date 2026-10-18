"""The audit log page (`/api/admin/audit*`, permission `audit`): every console action and
security event, filtered by actor, action, target, outcome and period, with what changed.

The log is append-only (a database trigger refuses changes), so there is nothing to change
here: only reads, in a read-only transaction.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.access import AdminContext, read_only_db, require_admin
from app.models.models import utcnow
from app.schemas.admin import AuditFacets, AuditPage, AuditQuery, SecuritySummary
from app.services.admin import audit

router = APIRouter()
read_audit = require_admin("audit")


@router.get("/audit", response_model=AuditPage)
async def list_audit(
    query: Annotated[AuditQuery, Query()],
    _ctx: AdminContext = Depends(read_audit),
    db: AsyncSession = Depends(read_only_db),
) -> AuditPage:
    total, rows = await audit.list_entries(db, query)
    return AuditPage.model_validate(
        {"total": total, "limit": query.limit, "offset": query.offset, "rows": rows}
    )


@router.get("/audit/facets", response_model=AuditFacets)
async def audit_facets(
    _ctx: AdminContext = Depends(read_audit),
    db: AsyncSession = Depends(read_only_db),
) -> AuditFacets:
    return AuditFacets.model_validate(await audit.facets(db))


@router.get("/audit/security", response_model=SecuritySummary)
async def security_summary(
    _ctx: AdminContext = Depends(read_audit),
    db: AsyncSession = Depends(read_only_db),
) -> SecuritySummary:
    return SecuritySummary.model_validate(await audit.security_summary(db, utcnow()))
