"""Network map, switch ports and device location (licence module: topology)."""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.licensing.enforcement import require_module
from backend.middleware.auth import get_current_user
from backend.models.device import Device
from backend.models.topology import MacLocation, NetworkPort
from backend.models.user import User
from backend.schemas.common import APIResponse
from backend.topology import service

router = APIRouter(prefix="/topology", tags=["Topology"], dependencies=[require_module("topology")])


async def _device(db: AsyncSession, device_id: int) -> Device:
    dev = await db.get(Device, device_id)
    if dev is None:
        raise HTTPException(404, "Device not found")
    return dev


@router.get("/graph", response_model=APIResponse[Dict[str, Any]])
async def topology_graph(endpoints: bool = False, vlan: Optional[int] = Query(None, ge=1, le=4094),
                         db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    data = await service.graph(db, include_endpoints=endpoints, vlan=vlan)
    data["stats"]["last_collected"] = await db.scalar(select(func.max(NetworkPort.last_seen)))
    data["stats"]["macs"] = await db.scalar(select(func.count(MacLocation.id))) or 0
    return APIResponse(data=data)


@router.get("/devices/{device_id}/ports", response_model=APIResponse[List[Dict[str, Any]]])
async def device_ports(device_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await _device(db, device_id)
    return APIResponse(data=await service.switch_ports(db, device_id))


@router.get("/devices/{device_id}/location", response_model=APIResponse[List[Dict[str, Any]]])
async def device_location(device_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return APIResponse(data=await service.locate(db, await _device(db, device_id)))
