from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Dict, Any

from backend.database import get_db
from backend.services.device_service import DeviceService
from backend.schemas.common import APIResponse
from backend.middleware.auth import get_current_user
from backend.models.connector_config import ConnectorConfig

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/summary", response_model=APIResponse[Dict[str, Any]])
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    stats = await DeviceService.get_dashboard_summary(db)
    return APIResponse(data=stats)

@router.get("/coverage-gaps", response_model=APIResponse[Dict[str, Any]])
async def get_coverage_gaps(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    Returns active devices that are missing from one or more enabled connectors.
    This identifies unmanaged assets — devices seen by AD but not by any AV/EDR, etc.
    """
    result = await db.execute(
        select(ConnectorConfig.connector_name)
        .where(ConnectorConfig.enabled == True)
    )
    enabled_sources = [row[0] for row in result.fetchall()]
    gaps = await DeviceService.get_coverage_gaps(db, enabled_sources)
    return APIResponse(data=gaps)
