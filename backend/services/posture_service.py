"""
CAASM posture: correlate vulnerabilities to assets, compute log-source
coverage gaps, and produce an overall control-coverage summary.
"""
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.asset import Asset
from backend.models.device_source import DeviceSource
from backend.models.vulnerability import Vulnerability

_SEV_WEIGHT = {"critical": 40, "high": 10, "medium": 3, "low": 1, "info": 0}


class PostureService:
    @staticmethod
    async def import_vulnerabilities(db: AsyncSession, rows: List[Dict[str, Any]]) -> Dict[str, int]:
        """Import findings; correlate to an asset by ip_address or asset_tag."""
        imported = unmatched = 0
        for r in rows:
            asset = None
            tag = (r.get("asset_tag") or "").strip()
            ip = (r.get("ip") or r.get("ip_address") or "").strip()
            if tag:
                asset = (await db.execute(select(Asset).where(Asset.asset_tag == tag))).scalars().first()
            if not asset and ip:
                asset = (await db.execute(select(Asset).where(Asset.ip_address == ip))).scalars().first()

            sev = (r.get("severity") or "medium").strip().lower()
            if sev not in _SEV_WEIGHT:
                sev = "medium"
            det: Optional[date] = None
            if r.get("detected_on"):
                try:
                    det = date.fromisoformat(r["detected_on"][:10])
                except (ValueError, TypeError):
                    det = None
            db.add(Vulnerability(
                asset_id=asset.id if asset else None,
                device_id=asset.device_id if asset else None,
                cve_id=(r.get("cve") or r.get("cve_id") or None),
                title=(r.get("title") or r.get("name") or "Unnamed finding")[:500],
                severity=sev,
                cvss=(str(r.get("cvss")) if r.get("cvss") else None),
                description=r.get("description"),
                detected_on=det,
            ))
            imported += 1
            if not asset:
                unmatched += 1
            # keep the asset's last-scan date fresh
            if asset and det and (asset.last_vulnerability_scan is None or det > asset.last_vulnerability_scan):
                asset.last_vulnerability_scan = det
        await db.commit()
        return {"imported": imported, "unmatched": unmatched}

    @staticmethod
    async def vulnerability_summary(db: AsyncSession) -> Dict[str, Any]:
        by_sev = dict((s, c) for s, c in (await db.execute(
            select(Vulnerability.severity, func.count(Vulnerability.id))
            .where(Vulnerability.status == "open").group_by(Vulnerability.severity)
        )).all())
        # Riskiest assets (weighted by severity, tie-broken by criticality)
        rows = (await db.execute(
            select(Asset.id, Asset.asset_tag, Asset.name, Asset.criticality, Vulnerability.severity, func.count())
            .join(Vulnerability, Vulnerability.asset_id == Asset.id)
            .where(Vulnerability.status == "open")
            .group_by(Asset.id, Asset.asset_tag, Asset.name, Asset.criticality, Vulnerability.severity)
        )).all()
        risk: Dict[int, Dict[str, Any]] = {}
        for aid, tag, name, crit, sev, cnt in rows:
            r = risk.setdefault(aid, {"asset_tag": tag, "name": name, "criticality": crit,
                                      "score": 0, "counts": {}})
            r["counts"][sev] = cnt
            r["score"] += _SEV_WEIGHT.get(sev, 0) * cnt
        top = sorted(risk.values(), key=lambda x: x["score"], reverse=True)[:15]
        return {
            "open_by_severity": {s: by_sev.get(s, 0) for s in _SEV_WEIGHT},
            "total_open": sum(by_sev.values()),
            "top_risk_assets": top,
        }

    @staticmethod
    async def log_source_coverage(db: AsyncSession) -> Dict[str, Any]:
        """Which active assets are/aren't onboarded as SIEM log sources."""
        assets = (await db.execute(
            select(Asset).where(Asset.lifecycle_state == "deployed")
        )).scalars().all()
        onboarded, missing = [], []
        for a in assets:
            entry = {"asset_tag": a.asset_tag, "name": a.name, "criticality": a.criticality,
                     "ip": a.ip_address, "status": a.log_source_status}
            if a.log_source_status == "onboarded":
                onboarded.append(entry)
            else:
                missing.append(entry)
        total = len(assets)
        return {
            "total_deployed": total,
            "onboarded": len(onboarded),
            "coverage_pct": round(100 * len(onboarded) / total, 1) if total else 0.0,
            "gaps": sorted(missing, key=lambda x: (x["criticality"] != "critical",
                                                   x["criticality"] != "high")),
        }

    @staticmethod
    async def summary(db: AsyncSession) -> Dict[str, Any]:
        total = (await db.scalar(select(func.count(Asset.id)))) or 0

        def pct(n): return round(100 * n / total, 1) if total else 0.0

        agent = (await db.scalar(
            select(func.count(func.distinct(Asset.id)))
            .join(DeviceSource, DeviceSource.device_id == Asset.device_id)
            .where(DeviceSource.source_name == "agent")
        )) or 0
        logging_on = (await db.scalar(
            select(func.count(Asset.id)).where(Asset.log_source_status == "onboarded")
        )) or 0
        classified = (await db.scalar(
            select(func.count(Asset.id)).where(Asset.data_classification.isnot(None))
        )) or 0
        scanned = (await db.scalar(
            select(func.count(Asset.id)).where(Asset.last_vulnerability_scan.isnot(None))
        )) or 0
        monitored = (await db.scalar(
            select(func.count(Asset.id)).where(Asset.monitoring_status == "monitored")
        )) or 0
        return {
            "total_assets": total,
            "controls": {
                "agent_coverage": {"count": agent, "pct": pct(agent)},
                "log_source_coverage": {"count": logging_on, "pct": pct(logging_on)},
                "data_classified": {"count": classified, "pct": pct(classified)},
                "vuln_scanned": {"count": scanned, "pct": pct(scanned)},
                "monitored": {"count": monitored, "pct": pct(monitored)},
            },
        }
