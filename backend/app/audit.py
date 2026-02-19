"""Audit Layer - log all analyses for clinical traceability."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

AUDIT_LOG_PATH = Path("audit_log.jsonl")


def audit_log(
    patient_id: str,
    analysis_id: str,
    vcf_hash: str,
    drugs: List[str],
    results: List[Dict[str, Any]],
) -> None:
    """Log analysis to file for hackathon. In production would use PostgreSQL."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "patient_id": patient_id,
        "analysis_id": analysis_id,
        "vcf_hash": vcf_hash,
        "drugs": drugs,
        "risk_summary": [
            {
                "drug": r.get("drug"),
                "risk_label": r.get("risk_assessment", {}).get("risk_label"),
                "confidence": r.get("risk_assessment", {}).get("confidence_score"),
            }
            for r in results
        ],
        "llm_version": "gpt-4o-mini",
    }
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        logger.warning("Audit log failed: %s", e)
