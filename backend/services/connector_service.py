from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Dict, Any
from backend.models.connector_config import ConnectorConfig
from backend.connectors.registry import registry
from backend.schemas.connector import ConnectorConfigCreate

class ConnectorService:
    @staticmethod
    async def get_all_status(db: AsyncSession) -> List[Dict[str, Any]]:
        """Returns the robust list of all avialable plugins and their DB config state."""
        # Get all registered plugins
        plugins = registry.list_connectors()
        
        # Get current DB configs
        result = await db.execute(select(ConnectorConfig))
        db_configs = {c.connector_name: c for c in result.scalars().all()}
        
        status_list = []
        for name, connector in plugins.items():
            db_conf = db_configs.get(name)
            status_list.append({
                "name": name,
                "display_name": connector.display_name,
                "is_configured": db_conf is not None,
                "is_enabled": db_conf.enabled if db_conf else False,
                "last_run": db_conf.last_run if db_conf else None,
                "last_status": db_conf.last_status if db_conf else None,
                "schema_definition": connector.get_config_schema(),
                "config": db_conf.config if db_conf else None
            })
            
        return status_list

    @staticmethod
    async def save_config(db: AsyncSession, name: str, config_data: ConnectorConfigCreate) -> ConnectorConfig:
        """Creates or updates a connector config."""
        result = await db.execute(select(ConnectorConfig).where(ConnectorConfig.connector_name == name))
        db_config = result.scalars().first()
        
        if db_config:
            db_config.config = config_data.config
            db_config.enabled = config_data.enabled
            db_config.schedule_cron = config_data.schedule_cron
        else:
            db_config = ConnectorConfig(
                connector_name=name,
                enabled=config_data.enabled,
                config=config_data.config,
                schedule_cron=config_data.schedule_cron
            )
            db.add(db_config)
            
        await db.commit()
        await db.refresh(db_config)
        return db_config

    @staticmethod
    async def get_config(db: AsyncSession, name: str) -> ConnectorConfig | None:
        result = await db.execute(select(ConnectorConfig).where(ConnectorConfig.connector_name == name))
        return result.scalars().first()
