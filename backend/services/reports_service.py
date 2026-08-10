"""Financial / lifecycle / compliance reports over the asset base."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.asset import Asset


class ReportsService:
    @staticmethod
    async def cost_summary(db: AsyncSession) -> Dict[str, Any]:
        total_cost = (await db.scalar(select(func.coalesce(func.sum(Asset.purchase_cost), 0)))) or 0
        by_cat = (await db.execute(
            select(Asset.category, func.count(Asset.id),
                   func.coalesce(func.sum(Asset.purchase_cost), 0))
            .group_by(Asset.category)
        )).all()
        by_dept = (await db.execute(
            select(func.coalesce(Asset.department, "Unassigned"), func.count(Asset.id),
                   func.coalesce(func.sum(Asset.purchase_cost), 0))
            .group_by(Asset.department)
        )).all()
        return {
            "total_capital": float(total_cost),
            "by_category": [{"category": c, "count": n, "cost": float(v)} for c, n, v in by_cat],
            "by_department": [{"department": d, "count": n, "cost": float(v)} for d, n, v in by_dept],
        }

    @staticmethod
    async def eol_forecast(db: AsyncSession, horizon_days: int = 365) -> Dict[str, Any]:
        today = date.today()
        horizon = today + timedelta(days=horizon_days)

        async def bucket(col):
            past = (await db.scalar(select(func.count(Asset.id)).where(col.isnot(None), col < today))) or 0
            soon = (await db.scalar(select(func.count(Asset.id)).where(col >= today, col <= horizon))) or 0
            return {"expired": past, "within_horizon": soon}

        eol = (await db.execute(
            select(Asset.asset_tag, Asset.name, Asset.eol_eos_date)
            .where(Asset.eol_eos_date.isnot(None), Asset.eol_eos_date <= horizon)
            .order_by(Asset.eol_eos_date)
        )).all()
        return {
            "horizon_days": horizon_days,
            "warranty": await bucket(Asset.warranty_end),
            "eol_eos": await bucket(Asset.eol_eos_date),
            "upcoming_eol": [{"asset_tag": t, "name": n, "eol_eos_date": d} for t, n, d in eol[:100]],
        }

    @staticmethod
    async def compliance_summary(db: AsyncSession) -> Dict[str, Any]:
        total = (await db.scalar(select(func.count(Asset.id)))) or 0

        def pct(n): return round(100 * n / total, 1) if total else 0.0

        crit = dict((c or "unset", n) for c, n in (await db.execute(
            select(func.coalesce(Asset.criticality, "unset"), func.count(Asset.id)).group_by(Asset.criticality)
        )).all())
        data_cls = dict((c or "unset", n) for c, n in (await db.execute(
            select(func.coalesce(Asset.data_classification, "unset"), func.count(Asset.id))
            .group_by(Asset.data_classification)
        )).all())
        with_owner = (await db.scalar(
            select(func.count(Asset.id)).where(Asset.point_of_contact.isnot(None))
        )) or 0
        reviewed = (await db.scalar(
            select(func.count(Asset.id)).where(Asset.last_reviewed_date.isnot(None))
        )) or 0
        return {
            "total_assets": total,
            "by_criticality": crit,
            "by_data_classification": data_cls,
            "with_owner_pct": pct(with_owner),
            "reviewed_pct": pct(reviewed),
        }
