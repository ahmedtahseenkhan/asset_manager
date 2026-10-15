"""
Agent enrollment tokens and report ingestion. Reports are parsed into an
InventoryReport (v1 flat payloads are upgraded) and handed to InventoryService.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent import AgentToken
from backend.schemas.inventory import InventoryReport
from backend.services.inventory_service import InventoryService

AGENT_SOURCE = "agent"

# Version shipped in agent/; reports from older agents are flagged as outdated.
LATEST_AGENT_VERSION = "2.0.0"


def _version_tuple(v: Optional[str]) -> tuple:
    try:
        return tuple(int(x) for x in (v or "").split("."))
    except ValueError:
        return (0,)      # "v1" and other pre-versioning agents


def is_outdated(version: Optional[str]) -> bool:
    return _version_tuple(version) < _version_tuple(LATEST_AGENT_VERSION)


def parse_agent_report(payload: Dict[str, Any]) -> InventoryReport:
    """v2+ payloads carry schema_version; anything else is the v1 flat format.
    Raises pydantic.ValidationError on malformed input."""
    if int(payload.get("schema_version") or 1) >= 2:
        return InventoryReport.model_validate(payload)
    return InventoryReport.from_v1(payload)


class AgentService:
    @staticmethod
    async def validate_token(db: AsyncSession, token: str) -> Optional[AgentToken]:
        if not token:
            return None
        row = (await db.execute(
            select(AgentToken).where(AgentToken.token == token, AgentToken.active == True)
        )).scalars().first()
        return row

    @staticmethod
    async def ingest(db: AsyncSession, token_row: AgentToken, report: InventoryReport) -> Dict[str, Any]:
        result = await InventoryService.ingest(db, AGENT_SOURCE, report)
        token_row.last_used_at = datetime.now(timezone.utc)
        token_row.reports_count = (token_row.reports_count or 0) + 1
        await db.commit()
        return result
