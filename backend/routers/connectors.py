from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Any
from backend.database import get_db
from backend.services.connector_service import ConnectorService
from backend.services.sync_service import SyncService
from backend.schemas.connector import ConnectorStatusOut, ConnectorConfigCreate, ConnectorConfigOut
from backend.schemas.common import APIResponse
from backend.middleware.auth import require_admin
from backend.connectors.registry import registry
from backend.services.scheduler_service import scheduler
from backend.services.audit_service import AuditService

router = APIRouter(prefix="/connectors", tags=["Connectors"])

@router.get("", response_model=APIResponse[List[Any]])
async def list_connectors(
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin)
):
    status_list = await ConnectorService.get_all_status(db)
    return APIResponse(data=status_list)

@router.post("/{name}/config", response_model=APIResponse[ConnectorConfigOut])
async def save_config(
    name: str,
    config_in: ConnectorConfigCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin)
):
    try:
        registry.get_connector(name)
    except ValueError:
        raise HTTPException(404, "Connector not found in registry")

    config = await ConnectorService.save_config(db, name, config_in)
    await scheduler.reload_jobs(db)
    await AuditService.log(db, request, admin, "connector.config_saved",
                           resource_type="connector", resource_id=name,
                           detail={"enabled": config_in.enabled, "schedule_cron": config_in.schedule_cron})
    return APIResponse(data=config)

@router.post("/{name}/test", response_model=APIResponse[bool])
async def test_connection(
    name: str,
    config_in: dict,
    admin=Depends(require_admin)
):
    try:
        connector = registry.get_connector(name)
        result = await connector.test_connection(config_in)
        return APIResponse(data=result, message="Connection test " + ("successful" if result else "failed"))
    except ValueError:
        raise HTTPException(404, "Connector not found")

@router.post("/{name}/sync", response_model=APIResponse[str])
async def trigger_sync(
    name: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    admin=Depends(require_admin)
):
    config = await ConnectorService.get_config(db, name)
    if not config:
        raise HTTPException(400, "Connector is not configured yet")

    await AuditService.log(db, request, admin, "connector.sync_triggered",
                           resource_type="connector", resource_id=name)

    async def bg_sync(config_id: int):
        async for session in get_db():
            await SyncService.run_sync_for_connector(session, config_id)

    background_tasks.add_task(bg_sync, config.id)
    return APIResponse(data="Sync started in background", message="ok")
