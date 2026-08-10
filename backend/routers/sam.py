from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.licensing.enforcement import require_module
from backend.middleware.auth import get_current_user
from backend.models.user import User
from backend.schemas.common import APIResponse
from backend.services.sam_service import SAMService

router = APIRouter(prefix="/sam", tags=["Software Asset Management"],
                   dependencies=[require_module("entitlements")])


@router.get("/software", response_model=APIResponse[List[Dict[str, Any]]])
async def software_inventory(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return APIResponse(data=await SAMService.software_inventory(db))


@router.get("/license-position", response_model=APIResponse[Dict[str, Any]])
async def license_position(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return APIResponse(data=await SAMService.license_position(db))
