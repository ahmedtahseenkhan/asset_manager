"""
Process-wide cached license state.

Loaded at startup (and after an admin uploads a new license). Requests read the
cached LicenseInfo — no per-request crypto or file IO.
"""
from __future__ import annotations

import logging
from pathlib import Path

from backend.config import settings
from backend.licensing.verifier import (
    LicenseInfo,
    LicenseStatus,
    verify_and_evaluate_file,
)

logger = logging.getLogger(__name__)


class LicenseManager:
    def __init__(self) -> None:
        self._info: LicenseInfo = LicenseInfo(LicenseStatus.MISSING, "License not loaded yet")

    @property
    def path(self) -> Path:
        return Path(settings.license_file)

    @property
    def current(self) -> LicenseInfo:
        return self._info

    def reload(self) -> LicenseInfo:
        self._info = verify_and_evaluate_file(self.path)
        if self._info.status is LicenseStatus.VALID:
            logger.info(
                "License OK: customer=%r expires=%s modules=%s",
                self._info.claims.get("customer"),
                self._info.claims.get("expires_at"),
                self._info.claims.get("modules"),
            )
        else:
            logger.warning("License state=%s: %s", self._info.status.value, self._info.reason)
        return self._info


license_manager = LicenseManager()
