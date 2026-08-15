"""Anomaly service: reads the persisted anomaly_report.json artifact."""

from __future__ import annotations

from . import cache

VALID_METHODS = {"rolling_zscore", "hourly_profile", "nighttime", "isolation_forest"}
VALID_SEVERITIES = {"moderate", "high", "critical"}


def anomalies(
    severity: str | None = None,
    method: str | None = None,
    limit: int = 500,
) -> dict:
    report = cache.load_anomaly_report()

    anomalies_list = list(report.get("anomalies") or [])

    def _match(item: dict) -> bool:
        if severity and item.get("severity") != severity:
            return False
        if method and item.get("method") != method:
            return False
        return True

    filtered = [a for a in anomalies_list if _match(a)][:limit]

    return {
        "generated_at": cache.utc_now(),
        "source": str(cache.ml_config.ANOMALY_REPORT),
        "artifact_generated_at": report.get("generated_at"),
        "configuration": report.get("configuration"),
        "counts_by_method": report.get("counts_by_method"),
        "counts_by_type": report.get("counts_by_type"),
        "counts_by_severity": report.get("counts_by_severity"),
        "filters": {"severity": severity, "method": method, "limit": limit},
        "returned": len(filtered),
        "total_matching": sum(1 for a in anomalies_list if _match(a)),
        "anomalies": filtered,
    }