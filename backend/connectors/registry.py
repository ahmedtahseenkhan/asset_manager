import logging
import importlib
import pkgutil
from typing import Dict, Type
import backend.connectors as connectors_pkg
from backend.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

class ConnectorRegistry:
    def __init__(self):
        self._connectors: Dict[str, BaseConnector] = {}

    def discover_and_register(self):
        """Discovers all modules inside backend/connectors and registers their BaseConnector implementations."""
        pkg_path = connectors_pkg.__path__
        
        for _, module_name, is_pkg in pkgutil.iter_modules(pkg_path):
            if is_pkg:
                # E.g., backend.connectors.ad
                full_module_name = f"backend.connectors.{module_name}.connector"
                try:
                    module = importlib.import_module(full_module_name)
                    # Look for classes that inherit from BaseConnector
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if isinstance(attr, type) and issubclass(attr, BaseConnector) and attr is not BaseConnector:
                            instance: BaseConnector = attr()
                            self._connectors[instance.name] = instance
                            logger.info(f"Registered connector: {instance.name}")
                            break
                except ImportError as e:
                    logger.warning(f"Could not load connector {module_name}: {e}")

    def get_connector(self, name: str) -> BaseConnector:
        if name not in self._connectors:
            raise ValueError(f"Connector '{name}' not found in registry.")
        return self._connectors[name]

    def list_connectors(self) -> Dict[str, BaseConnector]:
        return self._connectors

# Global registry instance
registry = ConnectorRegistry()
