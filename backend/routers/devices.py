from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.services.device_service import DeviceService
from backend.schemas.device import DeviceListOut, DeviceOut, DeviceFilter
from backend.schemas.common import APIResponse
from backend.middleware.auth import get_current_user
from backend.models.user import User

router = APIRouter(prefix="/devices", tags=["Devices"])

@router.get("", response_model=APIResponse[DeviceListOut])
async def list_devices(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    search: str = None,
    os_name: str = None,
    device_status: str = None, # renamed internally to avoid shadowed names
    health: str = None,        # endpoint-health filter, e.g. no_antivirus
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    f = DeviceFilter(search=search, os_name=os_name, status=device_status, health=health)
    try:
        total, devices = await DeviceService.get_devices(db, page, size, f)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    
    return APIResponse(data=DeviceListOut(
        items=devices,
        total=total,
        page=page,
        size=size
    ))

@router.get("/{device_id}", response_model=APIResponse[DeviceOut])
async def get_device(
    device_id: int, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    device = await DeviceService.get_device_by_id(db, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return APIResponse(data=device)
