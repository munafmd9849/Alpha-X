"""Pharmacogenomic variant database and gene coordinates.

EXACT mapping from specification - CPIC-aligned variant data.
GRCh37/hg19 coordinates.
"""

from typing import Dict, List, Optional, Tuple

# ============== GENE COORDINATES (GRCh37/hg19) ==============
GENE_COORDINATES: Dict[str, Tuple[str, int, int]] = {
    "CYP2D6": ("22", 42522894, 42526615),
    "CYP2C19": ("10", 94781859, 94789245),
    "CYP2C9": ("10", 94938905, 94943552),
    "VKORC1": ("16", 31102300, 31107345),  # CRITICAL for Warfarin
    "SLCO1B1": ("12", 21176894, 21245692),
    "TPMT": ("6", 18128763, 18156267),
    "DPYD": ("1", 97546827, 98340189),
}

# Chromosome name normalization (chr22 vs 22)
CHROM_ALIASES: Dict[str, str] = {
    "chr1": "1", "1": "1",
    "chr6": "6", "6": "6",
    "chr10": "10", "10": "10",
    "chr12": "12", "12": "12",
    "chr16": "16", "16": "16",
    "chr22": "22", "22": "22",
}

# ============== PGX VARIANT DATABASE - EXACT MAPPING ==============
PGX_VARIANTS: Dict[str, Dict[str, str]] = {
    # CYP2D6
    "rs1065852": {"gene": "CYP2D6", "allele": "*4", "function": "No function"},
    "rs3892097": {"gene": "CYP2D6", "allele": "*4", "function": "No function"},
    "rs5030655": {"gene": "CYP2D6", "allele": "*6", "function": "No function"},
    "rs5030867": {"gene": "CYP2D6", "allele": "*7", "function": "No function"},
    "rs16947": {"gene": "CYP2D6", "allele": "*2", "function": "Normal"},
    "rs28371706": {"gene": "CYP2D6", "allele": "*41", "function": "Decreased"},
    # CYP2C19
    "rs4244285": {"gene": "CYP2C19", "allele": "*2", "function": "No function"},
    "rs4986893": {"gene": "CYP2C19", "allele": "*3", "function": "No function"},
    "rs12248560": {"gene": "CYP2C19", "allele": "*17", "function": "Increased"},
    # CYP2C9
    "rs1799853": {"gene": "CYP2C9", "allele": "*2", "function": "Decreased"},
    "rs1057910": {"gene": "CYP2C9", "allele": "*3", "function": "Decreased"},
    # VKORC1 (CRITICAL for Warfarin)
    "rs9923231": {"gene": "VKORC1", "allele": "-1639A", "function": "Decreased expression"},
    "rs7294": {"gene": "VKORC1", "allele": "G", "function": "Increased expression"},
    # SLCO1B1
    "rs4149056": {"gene": "SLCO1B1", "allele": "*5", "function": "Decreased"},
    # TPMT
    "rs1800462": {"gene": "TPMT", "allele": "*2", "function": "No function"},
    "rs1800460": {"gene": "TPMT", "allele": "*3B", "function": "No function"},
    "rs1142345": {"gene": "TPMT", "allele": "*3C", "function": "No function"},
    # DPYD
    "rs3918290": {"gene": "DPYD", "allele": "*2A", "function": "No function"},
    "rs55886062": {"gene": "DPYD", "allele": "*13", "function": "No function"},
    "rs67376798": {"gene": "DPYD", "allele": "D949V", "function": "Decreased"},
}

# Position to RSID mapping (for minimal VCF - position-based lookup)
# Format: (chrom, pos) -> rsid
POSITION_TO_RSID: Dict[Tuple[str, int], str] = {}
for rsid, info in PGX_VARIANTS.items():
    gene = info["gene"]
    if gene in GENE_COORDINATES:
        chrom, start, end = GENE_COORDINATES[gene]
        # Use approximate positions - in production would use dbSNP
        # Key positions from dbSNP for these variants
        pass

# Manual position mappings for common variants (from dbSNP GRCh37)
POSITION_RSID_MAP: Dict[Tuple[str, int], str] = {
    # CYP2D6
    ("22", 42128936): "rs1065852",
    ("22", 42126611): "rs3892097",
    ("22", 42135590): "rs5030655",
    ("22", 42127611): "rs5030867",
    ("22", 42128936): "rs16947",  # same pos as rs1065852, different allele
    ("22", 42126613): "rs28371706",
    # CYP2C19
    ("10", 94762727): "rs4244285",
    ("10", 94761860): "rs4986893",
    ("10", 94780275): "rs12248560",
    # CYP2C9
    ("10", 94942090): "rs1799853",
    ("10", 94942254): "rs1057910",
    # VKORC1
    ("16", 31107682): "rs9923231",
    ("16", 31106923): "rs7294",
    # SLCO1B1
    ("12", 21178892): "rs4149056",
    # TPMT
    ("6", 18139228): "rs1800462",
    ("6", 18143594): "rs1800460",
    ("6", 18139228): "rs1142345",  # *3C
    # DPYD
    ("1", 97740426): "rs3918290",
    ("1", 97740642): "rs55886062",
    ("1", 97700019): "rs67376798",
}

# CYP2D6 Activity Score (CPIC standard)
CYP2D6_ALLELE_SCORES: Dict[str, float] = {
    "*1": 1.0, "*2": 1.0, "*35": 1.0,
    "*9": 0.5, "*10": 0.5, "*41": 0.5,
    "*4": 0.0, "*5": 0.0, "*6": 0.0, "*7": 0.0,
}

# Supported drugs and their gene(s)
DRUG_GENES: Dict[str, List[str]] = {
    "CODEINE": ["CYP2D6"],
    "CLOPIDOGREL": ["CYP2C19"],
    "WARFARIN": ["CYP2C9", "VKORC1"],
    "SIMVASTATIN": ["SLCO1B1"],
    "AZATHIOPRINE": ["TPMT"],
    "FLUOROURACIL": ["DPYD"],
}

SUPPORTED_DRUGS: List[str] = list(DRUG_GENES.keys())


def get_variant_info(rsid: str) -> Optional[Dict[str, str]]:
    """Get variant info by RSID."""
    return PGX_VARIANTS.get(rsid)


def get_rsid_by_position(chrom: str, pos: int) -> Optional[str]:
    """Get RSID by chromosome and position (for minimal VCF)."""
    chrom_norm = CHROM_ALIASES.get(chrom, chrom)
    return POSITION_RSID_MAP.get((chrom_norm, pos))


def gene_at_position(chrom: str, pos: int) -> Optional[str]:
    """Check if position falls within any target gene."""
    chrom_norm = CHROM_ALIASES.get(chrom, chrom)
    for gene, (g_chrom, start, end) in GENE_COORDINATES.items():
        if g_chrom == chrom_norm and start <= pos <= end:
            return gene
    return None
