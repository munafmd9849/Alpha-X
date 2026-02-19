"""Main analysis service - orchestrates VCF parsing, engine, LLM."""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from app.audit import audit_log
from app.database import DRUG_GENES, SUPPORTED_DRUGS
from app.engine import (
    compute_confidence,
    get_clinical_recommendation,
    infer_diplotype,
    predict_risk,
)
from app.llm import get_llm_explanation
from app.models import (
    ClinicalRecommendation,
    DrugAnalysisResult,
    LLMExplanation,
    PharmacogenomicProfile,
    QualityMetrics,
    RiskAssessment,
    UnsupportedDrugResult,
)
from app.vcf_parser import CNVResult, parse_vcf, validate_vcf_file, VCFParseResult

logger = logging.getLogger(__name__)


def analyze(
    vcf_path: Optional[str] = None,
    vcf_content: Optional[bytes] = None,
    drugs_str: str = "",
) -> Dict:
    """
    Main analysis entry point.
    Returns dict suitable for AnalysisResponse.
    """
    drugs = [d.strip().upper() for d in drugs_str.split(",") if d.strip()]
    if not drugs:
        drugs = ["CODEINE"]

    patient_id = f"PGX-{uuid4().hex[:12].upper()}"
    analysis_id = f"ANL-{uuid4().hex[:8].upper()}"

    # Validate VCF
    if vcf_path:
        err = validate_vcf_file(vcf_path)
    else:
        err = validate_vcf_file("", vcf_content)

    if err:
        raise ValueError(f"{err[0]}: {err[1]}")

    # Parse VCF
    parse_result = parse_vcf(file_path=vcf_path, content=vcf_content)
    if parse_result.errors:
        raise ValueError(parse_result.errors[0])

    # Build gene profiles for all target genes
    gene_profiles: Dict[str, Dict] = {}
    for gene, variants in parse_result.variants_by_gene.items():
        cnv = parse_result.cnv_by_gene.get(gene)
        diplo, pheno, score, cn = infer_diplotype(variants, cnv, gene)
        detected_rsids = [v.rsid for v in variants if v.rsid.startswith("rs")]
        gene_profiles[gene] = {
            "gene": gene,
            "diplotype": diplo,
            "phenotype": pheno,
            "activity_score": score,
            "copy_number": cn,
            "detected_variants": detected_rsids or [v.rsid for v in variants],
            "variant_count": len(variants),
        }

    # Fill in missing genes as *1/*1
    for gene in DRUG_GENES.values():
        for g in gene:
            if g not in gene_profiles:
                gene_profiles[g] = {
                    "gene": g,
                    "diplotype": "*1/*1",
                    "phenotype": "Normal Metabolizer (Assumed)",
                    "activity_score": 1.0,
                    "copy_number": None,
                    "detected_variants": [],
                    "variant_count": 0,
                }

    # Process each drug
    results: List = []
    interaction_warning = None

    for drug in drugs:
        if drug not in SUPPORTED_DRUGS:
            results.append(
                UnsupportedDrugResult(
                    drug=drug,
                    risk_assessment=RiskAssessment(
                        risk_label="Unknown",
                        confidence_score=0.0,
                        severity="none",
                    ),
                    clinical_recommendation=ClinicalRecommendation(
                        action="Drug not currently supported in CPIC database",
                        dose_adjustment=None,
                        monitoring="Consult clinical pharmacist",
                        alternative_drugs=None,
                    ),
                )
            )
            continue

        genes_needed = DRUG_GENES[drug]
        profiles_for_drug = {g: gene_profiles.get(g, {}) for g in genes_needed}
        primary_gene = genes_needed[0]

        # Primary gene profile for this drug
        pg = gene_profiles.get(primary_gene, {})
        variant_count = pg.get("variant_count", 0)
        detected = pg.get("detected_variants", [])

        # No variants case
        total_variants = sum(gene_profiles.get(g, {}).get("variant_count", 0) for g in genes_needed)
        if total_variants == 0 and "CYP2D6" not in parse_result.cnv_by_gene:
            results.append(
                DrugAnalysisResult(
                    drug=drug,
                    pharmacogenomic_profile=PharmacogenomicProfile(
                        gene=primary_gene,
                        diplotype="*1/*1",
                        phenotype="Normal Metabolizer (Assumed)",
                        detected_variants=[],
                    ),
                    risk_assessment=RiskAssessment(
                        risk_label="Safe",
                        confidence_score=0.6,
                        severity="none",
                    ),
                    clinical_recommendation=ClinicalRecommendation(
                        action="Standard dose recommended (no variants detected)",
                        dose_adjustment=None,
                        monitoring="Consider confirmatory testing if high-risk drug",
                        alternative_drugs=None,
                    ),
                    quality_metrics=QualityMetrics(
                        annotation_completeness="low",
                        variants_analyzed=0,
                        confidence_breakdown={
                            "variant_coverage": 0,
                            "annotation_quality": 0.3,
                            "cnv_detection": 0.7,
                            "cpic_evidence": 0.5,
                        },
                    ),
                )
            )
            continue

        confidence = compute_confidence(parse_result, primary_gene, variant_count)

        risk_label, severity, rationale = predict_risk(drug, gene_profiles)
        clin_rec = get_clinical_recommendation(drug, risk_label, gene_profiles)

        # Build pharmacogenomic profile
        pp = PharmacogenomicProfile(
            gene=primary_gene,
            diplotype=pg.get("diplotype", "*1/*1"),
            phenotype=pg.get("phenotype", "Normal Metabolizer"),
            detected_variants=detected,
            activity_score=pg.get("activity_score"),
            copy_number=pg.get("copy_number"),
        )
        if len(genes_needed) > 1:
            for g in genes_needed[1:]:
                gp = gene_profiles.get(g, {})
                pp.detected_variants.extend(gp.get("detected_variants", []))

        # LLM explanation (async-safe, with fallback)
        llm_expl = None
        try:
            llm_expl = get_llm_explanation(
                drug=drug,
                gene=primary_gene,
                diplotype=pp.diplotype,
                phenotype=pp.phenotype,
                risk=risk_label,
                variants=pp.detected_variants,
                recommendation=clin_rec.get("action", ""),
            )
        except Exception as e:
            logger.warning("LLM explanation failed: %s", e)
            llm_expl = LLMExplanation(
                summary="Unable to generate AI explanation. Based on CPIC guidelines, this genotype indicates significant drug interaction risk.",
                mechanism="Consult clinical decision support tool for detailed mechanism.",
                citation="CPIC Guidelines",
            )

        qm = QualityMetrics(
            annotation_completeness=parse_result.annotation_completeness,
            variants_analyzed=total_variants,
            confidence_breakdown={
                "variant_coverage": min(1.0, variant_count / 6),
                "annotation_quality": 1.0 if parse_result.annotation_completeness == "full" else 0.7,
                "cnv_detection": 0.7,
                "cpic_evidence": 0.8,
            },
            interaction_warning=interaction_warning,
        )

        results.append(
            DrugAnalysisResult(
                drug=drug,
                pharmacogenomic_profile=pp,
                risk_assessment=RiskAssessment(
                    risk_label=risk_label,
                    confidence_score=confidence,
                    severity=severity,
                    rationale=rationale,
                ),
                clinical_recommendation=ClinicalRecommendation(**clin_rec),
                quality_metrics=qm,
                llm_explanation=llm_expl,
            )
        )

    # Audit
    audit_log(
        patient_id=patient_id,
        analysis_id=analysis_id,
        vcf_hash=parse_result.vcf_hash,
        drugs=drugs,
        results=[r.model_dump() if hasattr(r, "model_dump") else r for r in results],
    )

    return {
        "patient_id": patient_id,
        "analysis_id": analysis_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "results": [r.model_dump() if hasattr(r, "model_dump") else r for r in results],
        "vcf_hash": parse_result.vcf_hash,
        "audit_id": analysis_id,
    }
