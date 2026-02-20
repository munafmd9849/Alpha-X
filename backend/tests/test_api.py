"""API and integration tests for PharmaGuard."""

import pytest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
FIXTURES = Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures"


def test_health():
    """Health check."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_list_drugs():
    """List supported drugs."""
    r = client.get("/drugs")
    assert r.status_code == 200
    drugs = r.json()["drugs"]
    assert "CODEINE" in drugs
    assert "WARFARIN" in drugs


def test_analyze_normal_metabolizer():
    """TEST 1: Normal metabolizer - Safe."""
    vcf = (FIXTURES / "normal_metabolizer.vcf").read_bytes()
    r = client.post(
        "/analyze",
        files={"file": ("normal.vcf", vcf, "text/plain")},
        data={"drugs": "CODEINE"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["results"][0]["risk_assessment"]["risk_label"] == "Safe"
    assert data["results"][0]["risk_assessment"]["confidence_score"] >= 0.7


def test_analyze_poor_metabolizer():
    """TEST 2: Poor metabolizer - Toxic."""
    vcf = (FIXTURES / "poor_metabolizer.vcf").read_bytes()
    r = client.post(
        "/analyze",
        files={"file": ("poor.vcf", vcf, "text/plain")},
        data={"drugs": "CODEINE"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["results"][0]["risk_assessment"]["risk_label"] == "Toxic"
    assert data["results"][0]["risk_assessment"]["severity"] == "high"


def test_analyze_ultra_rapid_metabolizer():
    """TEST 3: Ultra-rapid metabolizer (CYP2D6 duplication) - Toxic."""
    vcf = (FIXTURES / "ultra_rapid.vcf").read_bytes()
    r = client.post(
        "/analyze",
        files={"file": ("ultra_rapid.vcf", vcf, "text/plain")},
        data={"drugs": "CODEINE"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["results"][0]["risk_assessment"]["risk_label"] == "Toxic"
    pheno = data["results"][0]["pharmacogenomic_profile"]["phenotype"]
    assert "Ultra-rapid" in pheno or "URM" in pheno


def test_analyze_warfarin_intermediate():
    """TEST 4: Warfarin intermediate."""
    vcf = (FIXTURES / "warfarin_intermediate.vcf").read_bytes()
    r = client.post(
        "/analyze",
        files={"file": ("warfarin.vcf", vcf, "text/plain")},
        data={"drugs": "WARFARIN"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["results"][0]["risk_assessment"]["risk_label"] == "Adjust Dosage"
    assert data["results"][0]["risk_assessment"]["confidence_score"] > 0.7


def test_analyze_multiple_drugs():
    """TEST 5: Multiple drugs."""
    vcf = (FIXTURES / "normal_metabolizer.vcf").read_bytes()
    r = client.post(
        "/analyze",
        files={"file": ("normal.vcf", vcf, "text/plain")},
        data={"drugs": "CODEINE,CLOPIDOGREL,WARFARIN"},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["results"]) == 3


def test_analyze_no_variants():
    """TEST 6: No variants - assumed normal."""
    vcf = (FIXTURES / "no_variants.vcf").read_bytes()
    r = client.post(
        "/analyze",
        files={"file": ("no_var.vcf", vcf, "text/plain")},
        data={"drugs": "CODEINE"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["results"][0]["pharmacogenomic_profile"]["phenotype"] == "Normal Metabolizer (Assumed)"
    assert data["results"][0]["risk_assessment"]["confidence_score"] == 0.6


def test_analyze_minimal_vcf():
    """TEST 8: Missing INFO tags - partial annotation completeness."""
    vcf = (FIXTURES / "minimal.vcf").read_bytes()
    r = client.post(
        "/analyze",
        files={"file": ("minimal.vcf", vcf, "text/plain")},
        data={"drugs": "WARFARIN"},
    )
    assert r.status_code == 200
    data = r.json()
    qm = data["results"][0].get("quality_metrics", {})
    assert qm.get("annotation_completeness") == "partial"


def test_analyze_corrupted_vcf():
    """TEST 7: Corrupted VCF - 400."""
    vcf = (FIXTURES / "corrupted.vcf").read_bytes()
    r = client.post(
        "/analyze",
        files={"file": ("bad.vcf", vcf, "text/plain")},
        data={"drugs": "CODEINE"},
    )
    assert r.status_code == 400


def test_analyze_unsupported_drug():
    """TEST 9: Unsupported drug."""
    vcf = (FIXTURES / "normal_metabolizer.vcf").read_bytes()
    r = client.post(
        "/analyze",
        files={"file": ("normal.vcf", vcf, "text/plain")},
        data={"drugs": "IBUPROFEN"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["results"][0]["risk_assessment"]["risk_label"] == "Unknown"
    assert data["results"][0]["drug"] == "IBUPROFEN"


def test_analyze_tpmt_poor():
    """TEST 10: TPMT poor - critical."""
    vcf = (FIXTURES / "tpmt_poor.vcf").read_bytes()
    r = client.post(
        "/analyze",
        files={"file": ("tpmt.vcf", vcf, "text/plain")},
        data={"drugs": "AZATHIOPRINE"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["results"][0]["risk_assessment"]["risk_label"] == "Toxic"
    assert data["results"][0]["risk_assessment"]["severity"] == "critical"


def test_analyze_edge_cases():
    """Edge cases: multi-allelic, phased, SV, missing GT, unicode, etc."""
    vcf = (FIXTURES / "edge_cases.vcf").read_bytes()
    r = client.post(
        "/analyze",
        files={"file": ("edge_cases.vcf", vcf, "text/plain")},
        data={"drugs": "CODEINE,CLOPIDOGREL,WARFARIN,SIMVASTATIN,AZATHIOPRINE,FLUOROURACIL"},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["results"]) == 6
    # Key checks: parses without error, returns risk for all drugs
    by_drug = {x["drug"]: x for x in data["results"]}
    assert "CODEINE" in by_drug and by_drug["CODEINE"]["risk_assessment"]["risk_label"] in ("Toxic", "Safe", "Adjust Dosage", "Unknown")
    assert "FLUOROURACIL" in by_drug


def test_analyze_test_patient():
    """TEST: Multi-gene test patient - CYP2C19*2/*3, CYP2D6*4, SLCO1B1*5, TPMT*3A, DPYD*2A, CYP2C9*2/*3."""
    vcf = (FIXTURES / "test_patient.vcf").read_bytes()
    r = client.post(
        "/analyze",
        files={"file": ("test_patient.vcf", vcf, "text/plain")},
        data={"drugs": "CODEINE,CLOPIDOGREL,WARFARIN,SIMVASTATIN,AZATHIOPRINE,FLUOROURACIL"},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["results"]) == 6

    by_drug = {r["drug"]: r for r in data["results"]}
    assert by_drug["CODEINE"]["risk_assessment"]["risk_label"] == "Toxic"
    assert by_drug["CODEINE"]["risk_assessment"]["severity"] == "high"
    assert by_drug["CLOPIDOGREL"]["risk_assessment"]["risk_label"] == "Ineffective"
    assert by_drug["WARFARIN"]["risk_assessment"]["risk_label"] == "Adjust Dosage"
    assert by_drug["SIMVASTATIN"]["risk_assessment"]["risk_label"] == "Adjust Dosage"
    assert by_drug["AZATHIOPRINE"]["risk_assessment"]["risk_label"] == "Adjust Dosage"
    assert by_drug["FLUOROURACIL"]["risk_assessment"]["risk_label"] == "Toxic"
    assert by_drug["FLUOROURACIL"]["risk_assessment"]["severity"] == "critical"
