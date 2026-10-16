"""
Software Asset Management: Effective License Position (ELP).

Compares each entitlement's purchased rights against the actual installs found
by the agent (normalized software titles), producing a compliance position and
a true-up estimate — the core SAM reconciliation.
"""
from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.entitlement import Entitlement
from backend.models.software import InstalledSoftware
from backend.services.software_normalizer import normalize_software


class SAMService:
    @staticmethod
    async def software_inventory(db: AsyncSession) -> List[Dict[str, Any]]:
        """Aggregate installed software by normalized product with install counts."""
        rows = (await db.execute(
            select(
                InstalledSoftware.normalized_name,
                func.count(func.distinct(InstalledSoftware.device_id)).label("installs"),
                func.count(InstalledSoftware.id).label("copies"),
                func.max(InstalledSoftware.vendor), func.max(InstalledSoftware.category),
            )
            .where(InstalledSoftware.normalized_name.isnot(None),
                   InstalledSoftware.normalized_name != "")
            .group_by(InstalledSoftware.normalized_name)
            .order_by(func.count(func.distinct(InstalledSoftware.device_id)).desc())
        )).all()
        return [{"product": r[0], "installs": r[1], "copies": r[2], "vendor": r[3], "category": r[4]}
                for r in rows]

    @staticmethod
    async def _installs_for(db: AsyncSession, product: str) -> int:
        """Distinct devices with an install whose normalized title matches product."""
        norm = normalize_software(product)
        return (await db.scalar(
            select(func.count(func.distinct(InstalledSoftware.device_id)))
            .where(func.lower(InstalledSoftware.normalized_name) == norm.lower())
        )) or 0

    @staticmethod
    async def license_position(db: AsyncSession) -> Dict[str, Any]:
        """Effective License Position across all entitlements."""
        ents = (await db.execute(select(Entitlement))).scalars().all()
        positions = []
        total_gap = 0
        compliant = over = under = 0

        for e in ents:
            installs = await SAMService._installs_for(db, e.product)
            assigned = len(e.assignments)
            purchased = e.seats_purchased
            # "consumed" = the larger of discovered installs and manual assignments
            consumed = max(installs, assigned)

            if purchased is None:
                status = "unlimited"
                gap = 0
            elif consumed > purchased:
                status = "over-deployed"
                gap = consumed - purchased
                over += 1
                total_gap += gap
            elif consumed < purchased:
                status = "under-utilized"
                gap = consumed - purchased          # negative = spare seats
                under += 1
            else:
                status = "compliant"
                gap = 0
                compliant += 1

            positions.append({
                "entitlement_id": e.id,
                "product": e.product,
                "vendor": e.vendor,
                "license_model": e.license_model,
                "seats_purchased": purchased,
                "seats_assigned": assigned,
                "installs_discovered": installs,
                "consumed": consumed,
                "status": status,
                "gap": gap,
                "expires_on": e.expires_on,
            })

        return {
            "positions": positions,
            "summary": {
                "entitlements": len(ents),
                "compliant": compliant,
                "over_deployed": over,
                "under_utilized": under,
                "total_shortfall_seats": total_gap,   # seats needing true-up
            },
        }
