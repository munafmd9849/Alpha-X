"""PharmaGuard API - FastAPI with Pydantic validation."""

import logging
import tempfile
from pathlib import Path

import json
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import get_settings
from app.database import SUPPORTED_DRUGS
from app.models import AnalysisResponse
from app.service import analyze
from app.vcf_parser import validate_vcf_file, _decompress_if_gzipped

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="PharmaGuard API",
    description="Pharmacogenomics Clinical Decision Support System",
    version="1.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.get("/")
def root():
    """Health check."""
    return {"status": "ok", "service": "PharmaGuard", "version": "1.0.0"}


@app.get("/health")
def health():
    """Health check for deployment."""
    return {"status": "healthy"}


@app.get("/drugs")
def list_drugs():
    """List supported drugs."""
    return {"drugs": SUPPORTED_DRUGS}


@app.get("/results/{analysis_id}")
def get_results(analysis_id: str):
    """Fetch analysis results by ID for shareable links."""
    if analysis_id not in _results_store:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return _results_store[analysis_id]


@app.post("/regenerate-explanation")
@limiter.limit("20/minute")
async def regenerate_explanation(
    request: Request,
    analysis_id: str = Form(...),
    drug: str = Form(...),
):
    """Regenerate LLM explanation for a drug (calls LLM again)."""
    if analysis_id not in _results_store:
        raise HTTPException(status_code=404, detail="Analysis not found")
    data = _results_store[analysis_id]
    drug_upper = drug.upper().strip()
    result = next((r for r in data["results"] if r.get("drug") == drug_upper), None)
    if not result or "pharmacogenomic_profile" not in result:
        raise HTTPException(status_code=400, detail="Drug not found or unsupported")
    from app.llm import get_llm_explanation

    pp = result["pharmacogenomic_profile"]
    ra = result["risk_assessment"]
    cr = result["clinical_recommendation"]
    expl = get_llm_explanation(
        drug=drug_upper,
        gene=pp["gene"],
        diplotype=pp["diplotype"],
        phenotype=pp["phenotype"],
        risk=ra["risk_label"],
        variants=pp.get("detected_variants", []),
        recommendation=cr.get("action", ""),
    )
    result["llm_explanation"] = expl.model_dump() if expl else None
    return {"llm_explanation": result["llm_explanation"]}


@app.get("/audit/export")
def export_audit_csv():
    """Export clinical audit trail as CSV."""
    from app.audit import AUDIT_LOG_PATH
    import csv
    from io import StringIO

    if not AUDIT_LOG_PATH.exists():
        raise HTTPException(status_code=404, detail="No audit data yet")
    rows = []
    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                for r in entry.get("risk_summary", []):
                    rows.append({
                        "timestamp": entry.get("timestamp", ""),
                        "patient_id": entry.get("patient_id", ""),
                        "analysis_id": entry.get("analysis_id", ""),
                        "vcf_hash": entry.get("vcf_hash", ""),
                        "drug": r.get("drug", ""),
                        "risk_label": r.get("risk_label", ""),
                        "confidence": r.get("confidence", ""),
                    })
            except json.JSONDecodeError:
                continue
    if not rows:
        raise HTTPException(status_code=404, detail="No audit data")
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    from fastapi.responses import Response
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pharmaguard_audit.csv"},
    )


# In-memory store for shareable results (hackathon; use Redis/DB in production)
_results_store: dict = {}


def _validate_response(data: dict) -> AnalysisResponse:
    """Pre-response schema validation layer."""
    return AnalysisResponse.model_validate(data)


@app.post("/analyze", response_model=AnalysisResponse)
@limiter.limit("100/minute")
async def analyze_vcf(
    request: Request,
    file: UploadFile = File(...),
    drugs: str = Form(..., description="Comma-separated: CODEINE,WARFARIN,CLOPIDOGREL"),
):
    """
    Analyze VCF file for pharmacogenomic drug-gene interactions.
    """
    # File size check
    content = await file.read()
    if len(content) > settings.max_file_size:
        raise HTTPException(
            status_code=400,
            detail="File exceeds 5MB limit. Please provide a smaller VCF file.",
        )

    # Validate VCF (handles gzip, returns specific error)
    err = validate_vcf_file("", content)
    if err:
        code, msg = err
        raise HTTPException(status_code=400, detail=msg)

    # Decompress if gzipped, write temp file (cyvcf2 needs .vcf or .vcf.gz)
    content = _decompress_if_gzipped(content)
    suffix = ".vcf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        tf.write(content)
        tf.flush()
        path = tf.name

    try:
        result = analyze(vcf_path=path, drugs_str=drugs)
        validated = _validate_response(result)
        _results_store[validated.analysis_id] = validated.model_dump()
        return validated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(
            status_code=500,
            detail="Analysis failed. Please try again. If problem persists, contact support.",
        )
    finally:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
