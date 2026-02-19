"""Pydantic models for PharmaGuard API - EXACT schema matching requirements."""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


# ============== Risk Assessment ==============
class RiskAssessment(BaseModel):
    """Risk assessment for a drug-gene interaction."""

    risk_label: Literal[
        "Safe",
        "Adjust Dosage",
        "Toxic",
        "Ineffective",
        "Unknown",
    ]
    confidence_score: float = Field(ge=0, le=1)
    severity: Literal["none", "low", "moderate", "high", "critical"] = "none"
    rationale: Optional[str] = None


# ============== Clinical Recommendation ==============
class ClinicalRecommendation(BaseModel):
    """Clinical recommendation based on pharmacogenomic analysis."""

    action: str
    dose_adjustment: Optional[str] = None
    monitoring: Optional[str] = None
    alternative_drugs: Optional[List[str]] = None


# ============== Pharmacogenomic Profile ==============
class PharmacogenomicProfile(BaseModel):
    """Gene-specific pharmacogenomic profile."""

    gene: str
    diplotype: str
    phenotype: str
    detected_variants: List[str] = Field(default_factory=list)
    activity_score: Optional[float] = None
    copy_number: Optional[int] = None


# ============== Quality Metrics ==============
class QualityMetrics(BaseModel):
    """Quality metrics for the analysis."""

    annotation_completeness: Literal["full", "partial", "low"] = "full"
    variants_analyzed: int = 0
    confidence_breakdown: Optional[Dict[str, float]] = None
    interaction_warning: Optional[str] = None


# ============== LLM Explanation ==============
class LLMExplanation(BaseModel):
    """LLM-generated explanation (explains only, never decides)."""

    summary: str
    mechanism: str
    citation: str = "CPIC Guidelines"


# ============== Single Drug Analysis Result ==============
class DrugAnalysisResult(BaseModel):
    """Complete analysis result for a single drug."""

    drug: str
    pharmacogenomic_profile: PharmacogenomicProfile
    risk_assessment: RiskAssessment
    clinical_recommendation: ClinicalRecommendation
    quality_metrics: QualityMetrics
    llm_explanation: Optional[LLMExplanation] = None
    quality_metrics_extra: Optional[Dict[str, Any]] = None  # For interaction_warning


# ============== Unsupported Drug Response ==============
class UnsupportedDrugResult(BaseModel):
    """Response for unsupported drug."""

    drug: str
    risk_assessment: RiskAssessment
    clinical_recommendation: ClinicalRecommendation

    model_config = {"extra": "ignore"}


# ============== API Request ==============
class AnalysisRequest(BaseModel):
    """Request model - drugs as comma-separated string."""

    drugs: str = Field(..., description="Comma-separated drug names: CODEINE,WARFARIN,CLOPIDOGREL")


# ============== API Response ==============
class AnalysisResponse(BaseModel):
    """API response - array of drug analysis results."""

    patient_id: str
    analysis_id: str
    timestamp: str
    results: List[Union[DrugAnalysisResult, UnsupportedDrugResult]]
    vcf_hash: Optional[str] = None
    audit_id: Optional[str] = None


