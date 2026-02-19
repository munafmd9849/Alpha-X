"""Deterministic Rule Engine - CPIC-aligned, NO AI for decisions.

Diplotype inference, activity score calculation, risk prediction.
"""

import logging
from typing import Dict, List, Optional, Tuple

from app.database import (
    CYP2D6_ALLELE_SCORES,
    DRUG_GENES,
    PGX_VARIANTS,
    SUPPORTED_DRUGS,
)
from app.vcf_parser import CNVResult, ParsedVariant, VCFParseResult

logger = logging.getLogger(__name__)


# ============== DIPLOTYPE INFERENCE ==============
def infer_diplotype(
    variants: List[ParsedVariant],
    cnv: Optional[CNVResult] = None,
    gene: str = "",
) -> Tuple[str, str, Optional[float], Optional[int]]:
    """
    Infer diplotype, phenotype, activity score from variants.
    Returns: (diplotype, phenotype, activity_score, copy_number)
    """
    alleles: List[str] = []
    for v in variants:
        if v.allele and v.allele != "?":
            gt = (v.genotype or "1/1").replace("|", "/").strip()
            if gt in ("0/0", "0|0"):
                continue  # Ref/ref - sample doesn't have this allele
            if gt in ("1/1", "1|1"):
                alleles.extend([v.allele, v.allele])
            else:
                # 0/1, 1/0, etc - one copy
                alleles.append(v.allele)

    copy_number = cnv.copy_number if cnv else None

    if gene == "CYP2D6":
        return _infer_cyp2d6(alleles, cnv, variants)
    elif gene == "CYP2C19":
        return _infer_cyp2c19(alleles, variants)
    elif gene == "CYP2C9":
        return _infer_cyp2c9(alleles, variants)
    elif gene == "VKORC1":
        return _infer_vkorc1(alleles, variants)
    elif gene == "SLCO1B1":
        return _infer_slco1b1(alleles, variants)
    elif gene == "TPMT":
        return _infer_tpmt(alleles, variants)
    elif gene == "DPYD":
        return _infer_dpyd(alleles, variants)
    else:
        return ("*1/*1", "Normal Metabolizer", 1.0, None)


def _infer_cyp2d6(
    alleles: List[str],
    cnv: Optional[CNVResult],
    variants: List[ParsedVariant],
) -> Tuple[str, str, float, Optional[int]]:
    """CYP2D6 diplotype with activity score."""
    copy_number = cnv.copy_number if cnv else None

    # CNV handling
    if copy_number is not None:
        if copy_number > 2:
            return (f"*1x{copy_number}/*1", "Ultra-rapid metabolizer", 2.0, copy_number)
        if copy_number == 0:
            return ("*5/*5", "Poor metabolizer", 0.0, 0)

    # Collect unique star alleles (worst-case: assume one per chromosome if multiple)
    unique_alleles = list(dict.fromkeys(alleles))
    if not unique_alleles:
        return ("*1/*1", "Normal metabolizer", 1.0, copy_number)

    # Build diplotype - assume worst case for compound het
    if len(unique_alleles) == 1:
        a = unique_alleles[0]
        score = CYP2D6_ALLELE_SCORES.get(a, 0.5)
        total = score * 2
        if total == 0:
            pheno = "Poor metabolizer"
        elif total == 0.5:
            pheno = "Intermediate metabolizer"
        elif total <= 2.0:
            pheno = "Normal metabolizer"
        else:
            pheno = "Ultra-rapid metabolizer"
        return (f"{a}/{a}", pheno, total, copy_number)

    # Two different alleles
    a1, a2 = unique_alleles[0], unique_alleles[1]
    s1 = CYP2D6_ALLELE_SCORES.get(a1, 0.5)
    s2 = CYP2D6_ALLELE_SCORES.get(a2, 0.5)
    total = s1 + s2

    if total == 0:
        pheno = "Poor metabolizer"
    elif total == 0.5:
        pheno = "Intermediate metabolizer"
    elif total <= 2.0:
        pheno = "Normal metabolizer"
    else:
        pheno = "Ultra-rapid metabolizer"

    return (f"{a1}/{a2}", pheno, total, copy_number)


def _infer_cyp2c19(alleles: List[str], variants: List[ParsedVariant]) -> Tuple[str, str, Optional[float], None]:
    """CYP2C19: *2,*3 = no function; *17 = increased."""
    if not alleles:
        return ("*1/*1", "Normal metabolizer", None, None)
    unique = list(dict.fromkeys(alleles))
    no_func = {"*2", "*3"}
    inc = {"*17"}
    has_no = any(a in no_func for a in unique)
    has_inc = any(a in inc for a in unique)
    if has_no and has_inc:
        return (f"{unique[0]}/{unique[1]}", "Intermediate metabolizer", None, None)
    if len(unique) == 2 and all(a in no_func for a in unique):
        return (f"{unique[0]}/{unique[1]}", "Poor metabolizer", None, None)
    if has_inc and not has_no:
        return (f"{unique[0]}/{unique[1]}" if len(unique) > 1 else f"{unique[0]}/*1", "Rapid metabolizer", None, None)
    if has_no:
        return (f"{unique[0]}/{unique[1]}" if len(unique) > 1 else f"{unique[0]}/*1", "Intermediate metabolizer", None, None)
    return (f"{unique[0]}/{unique[1]}" if len(unique) > 1 else f"{unique[0]}/*1", "Normal metabolizer", None, None)


def _infer_cyp2c9(alleles: List[str], variants: List[ParsedVariant]) -> Tuple[str, str, Optional[float], None]:
    """CYP2C9: *2,*3 = decreased."""
    if not alleles:
        return ("*1/*1", "Normal metabolizer", None, None)
    unique = list(dict.fromkeys(alleles))
    dec = {"*2", "*3"}
    count_dec = sum(1 for a in unique if a in dec)
    if count_dec >= 2:
        return (f"{unique[0]}/{unique[1]}", "Poor metabolizer", None, None)
    if count_dec == 1:
        return (f"{unique[0]}/*1", "Intermediate metabolizer", None, None)
    return (f"{unique[0]}/{unique[1]}" if len(unique) > 1 else f"{unique[0]}/*1", "Normal metabolizer", None, None)


def _infer_vkorc1(alleles: List[str], variants: List[ParsedVariant]) -> Tuple[str, str, Optional[float], None]:
    """VKORC1: -1639A = decreased expression; G = increased."""
    if not alleles:
        return ("ref/ref", "Normal", None, None)
    unique = list(dict.fromkeys(alleles))
    if any("-1639A" in str(a) for a in unique):
        if len(unique) >= 2:
            return ("-1639A/-1639A", "Sensitive", None, None)
        return ("-1639A/ref", "Sensitive", None, None)
    return ("ref/ref", "Normal", None, None)


def _infer_slco1b1(alleles: List[str], variants: List[ParsedVariant]) -> Tuple[str, str, Optional[float], None]:
    """SLCO1B1: *5 = decreased."""
    if not alleles:
        return ("*1/*1", "Normal function", None, None)
    unique = list(dict.fromkeys(alleles))
    if "*5" in unique:
        if len(unique) >= 2 and "*5" in unique:
            return ("*5/*5", "Poor function", None, None)
        return ("*1/*5", "Intermediate function", None, None)
    return (f"{unique[0]}/{unique[1]}" if len(unique) > 1 else f"{unique[0]}/*1", "Normal function", None, None)


def _infer_tpmt(alleles: List[str], variants: List[ParsedVariant]) -> Tuple[str, str, Optional[float], None]:
    """TPMT: *2,*3B,*3C = no function."""
    if not alleles:
        return ("*1/*1", "Normal metabolizer", None, None)
    unique = list(dict.fromkeys(alleles))
    no_func = {"*2", "*3A", "*3B", "*3C", "*3"}
    count = sum(1 for a in unique if a in no_func)
    if count >= 2:
        return (f"{unique[0]}/{unique[1]}", "Poor metabolizer", None, None)
    if count == 1:
        return (f"{unique[0]}/*1", "Intermediate metabolizer", None, None)
    return ("*1/*1", "Normal metabolizer", None, None)


def _infer_dpyd(alleles: List[str], variants: List[ParsedVariant]) -> Tuple[str, str, Optional[float], None]:
    """DPYD: *2A,*13 = no function; D949V = decreased."""
    if not alleles:
        return ("*1/*1", "Normal metabolizer", None, None)
    unique = list(dict.fromkeys(alleles))
    no_func = {"*2A", "*13"}
    dec = {"D949V"}
    has_no = any(a in no_func for a in unique)
    has_dec = any(a in dec for a in unique)
    if has_no:
        return (f"{unique[0]}/{unique[1]}" if len(unique) > 1 else f"{unique[0]}/*1", "Poor metabolizer", None, None)
    if has_dec:
        return (f"{unique[0]}/*1", "Intermediate metabolizer", None, None)
    return ("*1/*1", "Normal metabolizer", None, None)


# ============== CONFIDENCE SCORE ==============
def compute_confidence(
    parse_result: VCFParseResult,
    gene: str,
    variant_count: int,
    cpic_level: float = 1.0,
) -> float:
    """
    confidence = (variant_coverage × 0.3) + (annotation_quality × 0.3) + (cnv_detection × 0.2) + (cpic_evidence × 0.2)
    """
    # Expected variants per gene (approximate)
    expected = {"CYP2D6": 6, "CYP2C19": 3, "CYP2C9": 2, "VKORC1": 2, "SLCO1B1": 1, "TPMT": 3, "DPYD": 3}
    exp = expected.get(gene, 3)
    variant_coverage = min(1.0, variant_count / max(1, exp))

    if parse_result.annotation_completeness == "full":
        annotation_quality = 1.0
    elif parse_result.annotation_completeness == "partial":
        annotation_quality = 0.7
    else:
        annotation_quality = 0.3

    if gene == "CYP2D6" and gene in parse_result.cnv_by_gene:
        cnv_detection = 1.0
    elif gene == "CYP2D6":
        cnv_detection = 0.7
    else:
        cnv_detection = 0.7

    cpic_evidence = cpic_level

    return round(
        (variant_coverage * 0.3)
        + (annotation_quality * 0.3)
        + (cnv_detection * 0.2)
        + (cpic_evidence * 0.2),
        2,
    )


# ============== RISK PREDICTION ENGINE ==============
def predict_risk(
    drug: str,
    gene_profiles: Dict[str, Dict],
) -> Tuple[str, str, str]:  # risk_label, severity, rationale
    """Determine risk from gene profiles. EXACT mappings from spec."""
    drug = drug.upper().strip()
    if drug not in SUPPORTED_DRUGS:
        return ("Unknown", "none", "Drug not supported")

    genes = DRUG_GENES.get(drug, [])

    if drug == "CODEINE":
        p = gene_profiles.get("CYP2D6", {})
        pheno = p.get("phenotype", "Normal metabolizer")
        if "Poor" in pheno or "PM" in pheno:
            return ("Toxic", "high", "Morphine toxicity risk in poor metabolizer")
        if "Intermediate" in pheno or "IM" in pheno:
            return ("Adjust Dosage", "moderate", "Reduce by 50%")
        if "Normal" in pheno or "NM" in pheno:
            return ("Safe", "none", "Standard dose")
        if "Ultra-rapid" in pheno or "URM" in pheno or "UM" in pheno:
            return ("Toxic", "high", "Life-threatening toxicity in ultra-rapid metabolizer")
        return ("Unknown", "low", "Phenotype unclear")

    if drug == "CLOPIDOGREL":
        p = gene_profiles.get("CYP2C19", {})
        pheno = p.get("phenotype", "Normal metabolizer")
        if "Poor" in pheno or "PM" in pheno:
            return ("Ineffective", "high", "Use alternative")
        if "Intermediate" in pheno or "IM" in pheno:
            return ("Adjust Dosage", "moderate", "Consider doubling dose")
        return ("Safe", "none", "Standard therapy")

    if drug == "WARFARIN":
        cyp = gene_profiles.get("CYP2C9", {})
        vkor = gene_profiles.get("VKORC1", {})
        cyp_pheno = cyp.get("phenotype", "Normal metabolizer")
        vkor_pheno = vkor.get("phenotype", "Normal")

        cyp_sensitive = "Poor" in cyp_pheno or "Intermediate" in cyp_pheno or "Decreased" in cyp_pheno
        cyp_poor = "Poor" in cyp_pheno
        vkor_sensitive = "Sensitive" in vkor_pheno

        if cyp_poor and vkor_sensitive:
            return ("Toxic", "critical", "Reduce 50% + monitor closely")
        if cyp_sensitive and vkor_sensitive:
            return ("Adjust Dosage", "high", "Reduce 40%")
        if cyp_sensitive and not vkor_sensitive:
            return ("Adjust Dosage", "moderate", "Reduce 30%")
        if not cyp_sensitive and vkor_sensitive:
            return ("Adjust Dosage", "moderate", "Reduce 20%")
        return ("Safe", "none", "Standard dose")

    if drug == "SIMVASTATIN":
        p = gene_profiles.get("SLCO1B1", {})
        pheno = p.get("phenotype", "Normal function")
        if "Poor" in pheno:
            return ("Toxic", "high", "Consider alternative")
        if "Intermediate" in pheno:
            return ("Adjust Dosage", "moderate", "Reduce dose, monitor CK")
        return ("Safe", "none", "Standard dose")

    if drug == "AZATHIOPRINE":
        p = gene_profiles.get("TPMT", {})
        pheno = p.get("phenotype", "Normal metabolizer")
        if "Poor" in pheno:
            return ("Toxic", "critical", "Alternative required - life-threatening toxicity risk")
        if "Intermediate" in pheno:
            return ("Adjust Dosage", "high", "Reduce 30-70%")
        return ("Safe", "none", "Standard dose")

    if drug == "FLUOROURACIL":
        p = gene_profiles.get("DPYD", {})
        pheno = p.get("phenotype", "Normal metabolizer")
        if "Poor" in pheno:
            return ("Toxic", "critical", "Contraindicated - severe toxicity risk")
        if "Intermediate" in pheno:
            return ("Adjust Dosage", "high", "Reduce 50%")
        return ("Safe", "none", "Standard dose")

    return ("Unknown", "none", "Drug not in database")


def get_clinical_recommendation(
    drug: str,
    risk_label: str,
    gene_profiles: Dict[str, Dict],
) -> Dict:
    """Build clinical recommendation from risk."""
    drug = drug.upper().strip()

    if risk_label == "Safe":
        return {
            "action": "Standard dose recommended",
            "dose_adjustment": None,
            "monitoring": "Routine monitoring as per standard care",
            "alternative_drugs": None,
        }
    if risk_label == "Adjust Dosage":
        actions = {
            "CODEINE": "Reduce dose by 50%",
            "CLOPIDOGREL": "Consider doubling maintenance dose or alternative",
            "WARFARIN": "Reduce initial dose; frequent INR monitoring",
            "SIMVASTATIN": "Reduce dose; monitor creatine kinase",
            "AZATHIOPRINE": "Reduce dose by 30-70%",
            "FLUOROURACIL": "Reduce dose by 50%",
        }
        return {
            "action": actions.get(drug, "Adjust dose based on genotype"),
            "dose_adjustment": actions.get(drug),
            "monitoring": "Increased monitoring recommended",
            "alternative_drugs": None,
        }
    if risk_label == "Toxic":
        alts = {
            "CODEINE": ["Tramadol", "Morphine", "Oxycodone"],
            "CLOPIDOGREL": ["Prasugrel", "Ticagrelor"],
            "SIMVASTATIN": ["Pravastatin", "Rosuvastatin"],
            "AZATHIOPRINE": ["6-mercaptopurine (at reduced dose)", "Mycophenolate"],
            "FLUOROURACIL": ["Consider DPYD testing", "Alternative regimen"],
        }
        return {
            "action": "Avoid or use alternative - significant toxicity risk",
            "dose_adjustment": None,
            "monitoring": "If must use: intensive monitoring",
            "alternative_drugs": alts.get(drug),
        }
    if risk_label == "Ineffective":
        return {
            "action": "Use alternative antiplatelet - clopidogrel may be ineffective",
            "dose_adjustment": None,
            "monitoring": None,
            "alternative_drugs": ["Prasugrel", "Ticagrelor"],
        }
    if risk_label == "Unknown":
        return {
            "action": "Drug not currently supported in CPIC database",
            "dose_adjustment": None,
            "monitoring": "Consult clinical pharmacist",
            "alternative_drugs": None,
        }

    return {
        "action": "Consult clinical pharmacist",
        "dose_adjustment": None,
        "monitoring": "Consult clinical pharmacist",
        "alternative_drugs": None,
    }
