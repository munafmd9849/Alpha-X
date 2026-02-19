"""VCF Parsing Layer - Streaming, memory-efficient with cyvcf2.

Handles all 6 real-world scenarios:
1. Standard VCF with INFO tags (GENE, STAR, RS)
2. Minimal VCF (position-based lookup)
3. Multi-allelic sites
4. Structural variants (CYP2D6 CNV)
5. Missing genotype FORMAT
6. Corrupted VCF validation
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from app.database import (
    GENE_COORDINATES,
    PGX_VARIANTS,
    gene_at_position,
    get_rsid_by_position,
)

logger = logging.getLogger(__name__)

# VCF validation error codes
VCF_ERROR_CODES = {
    "VCF_001": "Missing or invalid file format header (must start with ##fileformat)",
    "VCF_002": "No data lines found in VCF file",
    "VCF_003": "Invalid column count (minimum 8 required: CHROM, POS, ID, REF, ALT, QUAL, FILTER, INFO)",
    "VCF_004": "Invalid chromosome name in variant",
    "VCF_005": "Unable to parse VCF structure",
}


@dataclass
class ParsedVariant:
    """Single variant extracted from VCF."""

    rsid: str
    gene: str
    allele: str
    function: str
    chrom: str
    pos: int
    ref: str
    alt: str
    genotype: Optional[str] = None
    copy_number: Optional[int] = None
    source: str = "info"  # info, position, cnv


@dataclass
class CNVResult:
    """Copy number variant result."""

    gene: str
    copy_number: int
    confidence: str  # explicit, inferred, unknown


@dataclass
class VCFParseResult:
    """Complete VCF parsing result."""

    variants_by_gene: Dict[str, List[ParsedVariant]] = field(default_factory=dict)
    cnv_by_gene: Dict[str, CNVResult] = field(default_factory=dict)
    annotation_completeness: str = "full"
    vcf_hash: str = ""
    sample_genotypes: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


def _compute_vcf_hash(file_path: str, content: Optional[bytes] = None) -> str:
    """Compute SHA256 hash of VCF for audit trail."""
    hasher = hashlib.sha256()
    if content:
        hasher.update(content)
    else:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
    return hasher.hexdigest()[:16]


def _extract_rsid_from_id(id_field: str) -> Optional[str]:
    """Extract RSID from ID field (may contain multiple IDs)."""
    if not id_field or id_field == ".":
        return None
    # Could be rs123;rs456 or just rs123
    for part in id_field.split(";"):
        part = part.strip()
        if part.startswith("rs") and part[2:].isdigit():
            return part
    return None


def _parse_info_rs(info: str) -> Optional[str]:
    """Parse RS from INFO field."""
    match = re.search(r"RS=([^\s;]+)", info, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _parse_info_gene(info: str) -> Optional[str]:
    """Parse GENE from INFO field."""
    match = re.search(r"GENE=([^\s;]+)", info, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _parse_info_cn(info: str) -> Optional[int]:
    """Parse CN (copy number) from INFO field."""
    match = re.search(r"CN=(\d+)", info, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"CNV=(\d+)", info, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _parse_info_star(info: str) -> Optional[str]:
    """Parse STAR allele from INFO field."""
    match = re.search(r"STAR=([^\s;*]+)", info, re.IGNORECASE)
    if match:
        star = match.group(1).strip()
        return f"*{star}" if not star.startswith("*") else star
    return None


def _normalize_chrom(chrom: str) -> str:
    """Normalize chromosome name."""
    chrom = str(chrom).replace("chr", "").strip()
    return chrom


def validate_vcf_file(file_path: str, content: Optional[bytes] = None) -> Optional[Tuple[str, str]]:
    """Validate VCF file structure. Returns (error_code, message) or None if valid."""
    try:
        lines = []
        if content:
            text = content.decode("utf-8", errors="replace")
            lines = text.split("\n")[:500]  # Check first 500 lines
        else:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i >= 500:
                        break
                    lines.append(line)

        has_format = False
        has_header = False
        col_count = 0
        data_line_count = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("##fileformat"):
                has_format = True
                continue
            if line.startswith("#CHROM") or line.startswith("CHROM"):
                has_header = True
                parts = line.split("\t")
                col_count = len(parts)
                continue
            if has_header and not line.startswith("#"):
                data_line_count += 1
                if col_count == 0:
                    parts = line.split("\t")
                    col_count = len(parts)
                break

        if not has_format:
            return ("VCF_001", VCF_ERROR_CODES["VCF_001"])
        if data_line_count == 0:
            # Need to count data lines
            for line in lines:
                if line and not line.startswith("#") and has_header:
                    data_line_count += 1
            if data_line_count == 0:
                return ("VCF_002", VCF_ERROR_CODES["VCF_002"])
        if col_count < 8:
            return ("VCF_003", VCF_ERROR_CODES["VCF_003"])

        return None
    except Exception as e:
        logger.exception("VCF validation failed")
        return ("VCF_005", f"{VCF_ERROR_CODES['VCF_005']}: {str(e)}")


def parse_vcf(
    file_path: Optional[str] = None,
    content: Optional[bytes] = None,
) -> VCFParseResult:
    """
    Parse VCF file using cyvcf2 (streaming).

    Handles: standard INFO, minimal VCF, multi-allelic, CNV, missing genotype.
    """
    result = VCFParseResult()
    result.variants_by_gene = {g: [] for g in GENE_COORDINATES}

    # Get content for hash
    if content:
        vcf_content = content
        result.vcf_hash = hashlib.sha256(content).hexdigest()[:16]
    else:
        with open(file_path, "rb") as f:
            vcf_content = f.read()
        result.vcf_hash = hashlib.sha256(vcf_content).hexdigest()[:16]

    # Validate first
    if file_path:
        validation_error = validate_vcf_file(file_path)
    else:
        validation_error = validate_vcf_file("", content)

    if validation_error:
        result.errors.append(f"{validation_error[0]}: {validation_error[1]}")
        return result

    # Write temp file if we have content only (cyvcf2 needs file path)
    temp_path: Optional[str] = None
    parse_path = file_path
    if not file_path and content:
        import tempfile
        import os
        fd, temp_path = tempfile.mkstemp(suffix=".vcf")
        try:
            os.write(fd, content)
        finally:
            os.close(fd)
        parse_path = temp_path
    elif file_path:
        parse_path = file_path

    try:
        import cyvcf2

        vcf = cyvcf2.VCF(parse_path)
        seen_rsids: Set[Tuple[str, str]] = set()
        has_info_annotations = False
        position_based_count = 0

        for variant in vcf:
            chrom = _normalize_chrom(variant.CHROM)
            pos = int(variant.POS)
            ref = str(variant.REF or "")
            alts_raw = variant.ALT
            if alts_raw is None:
                alts = []
            elif isinstance(alts_raw, (list, tuple)):
                alts = [str(a) for a in alts_raw]
            else:
                alts = [str(alts_raw)]
            info = variant.INFO or {}

            # Scenario 4: Structural variants - SVTYPE, CN, CNV in INFO
            svtype = info.get("SVTYPE")
            cn_val = info.get("CN") or info.get("CNV")
            if cn_val is not None and (svtype or gene_at_position(chrom, pos) == "CYP2D6"):
                cn = int(cn_val) if isinstance(cn_val, (int, float)) else 0
                result.cnv_by_gene["CYP2D6"] = CNVResult(
                    gene="CYP2D6", copy_number=cn, confidence="explicit"
                )

            # Check FORMAT for CN/CNV
            try:
                fmt = variant.FORMAT or ""
                if "CN" in fmt or "CNV" in fmt:
                    cn_fmt = variant.format("CN") if "CN" in fmt else variant.format("CNV")
                    if cn_fmt is not None and cn_fmt.size > 0:
                        cn = int(cn_fmt.flat[0])
                        gene = _parse_info_gene(str(info)) or gene_at_position(chrom, pos)
                        if gene == "CYP2D6":
                            result.cnv_by_gene["CYP2D6"] = CNVResult(
                                gene="CYP2D6", copy_number=cn, confidence="explicit"
                            )
            except (KeyError, IndexError, TypeError, ValueError, AttributeError):
                pass

            # Get genotype - Scenario 5
            genotype_str = None
            if hasattr(variant, "genotypes") and variant.genotypes is not None and len(variant.genotypes) > 0:
                gt = variant.genotypes[0]
                if gt is not None and len(gt) >= 2:
                    a1, a2 = gt[0], gt[1]
                    if a1 is not None and a2 is not None:
                        genotype_str = f"{a1}/{a2}"
            if not genotype_str and hasattr(variant, "gt_bases") and variant.gt_bases:
                genotype_str = str(variant.gt_bases[0]).replace("|", "/")

            # Get RSID - Scenario 1 vs 2
            rsid = _parse_info_rs(str(info))
            if not rsid:
                rsid = _extract_rsid_from_id(str(variant.ID or ""))
            if not rsid:
                rsid = get_rsid_by_position(chrom, pos)
                if rsid:
                    position_based_count += 1

            gene_from_info = _parse_info_gene(str(info))
            gene = gene_from_info or gene_at_position(chrom, pos)

            if gene_from_info or (rsid and rsid in PGX_VARIANTS):
                has_info_annotations = True

            if not gene:
                continue

            if gene not in result.variants_by_gene:
                result.variants_by_gene[gene] = []

            # Scenario 3: Multi-allelic - check each alt
            for alt in (alts if alts else ["."]):
                if rsid and rsid in PGX_VARIANTS:
                    info_map = PGX_VARIANTS[rsid]
                    if (rsid, gene) not in seen_rsids:
                        seen_rsids.add((rsid, gene))
                        result.variants_by_gene[gene].append(
                            ParsedVariant(
                                rsid=rsid,
                                gene=gene,
                                allele=info_map["allele"],
                                function=info_map["function"],
                                chrom=chrom,
                                pos=pos,
                                ref=ref,
                                alt=alt,
                                genotype=genotype_str,
                                source="info" if (gene_from_info or rsid in PGX_VARIANTS) else "position",
                            )
                        )
                elif gene:
                    pos_key = (f"{chrom}:{pos}", gene)
                    if pos_key not in seen_rsids:
                        seen_rsids.add(pos_key)
                        result.variants_by_gene[gene].append(
                            ParsedVariant(
                                rsid=rsid or f"{chrom}:{pos}",
                                gene=gene,
                                allele="?",
                                function="Unknown",
                                chrom=chrom,
                                pos=pos,
                                ref=ref,
                                alt=alt,
                                genotype=genotype_str,
                                source="position",
                            )
                        )
                        result.annotation_completeness = "partial"

        vcf.close()

        # Determine annotation completeness
        if position_based_count > 0 and not has_info_annotations:
            result.annotation_completeness = "partial"
        elif not any(result.variants_by_gene.values()) and not result.cnv_by_gene:
            result.annotation_completeness = "low"

    except ImportError:
        # Fallback: parse manually without cyvcf2
        raw = content if content else (Path(file_path).read_bytes() if file_path else b"")
        result = _parse_vcf_manual(raw)
        result.vcf_hash = hashlib.sha256(raw).hexdigest()[:16]
    except Exception as e:
        logger.exception("VCF parse error")
        result.errors.append(f"Parse error: {str(e)}")
    finally:
        if temp_path:
            import os
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    return result


def _parse_vcf_manual(content: bytes) -> VCFParseResult:
    """Manual VCF parser fallback when cyvcf2 not available."""
    result = VCFParseResult()
    result.variants_by_gene = {g: [] for g in GENE_COORDINATES}

    text = content.decode("utf-8", errors="replace")
    lines = text.split("\n")

    in_data = False
    col_count = 0
    sample_start = 9

    for line in lines:
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("##fileformat"):
            continue
        if line.startswith("#CHROM") or line.startswith("CHROM"):
            parts = line.split("\t")
            col_count = len(parts)
            in_data = True
            continue
        if line.startswith("#"):
            continue
        if not in_data:
            continue

        parts = line.split("\t")
        if len(parts) < 8:
            continue

        chrom = _normalize_chrom(parts[0])
        pos = int(parts[1]) if parts[1].isdigit() else 0
        id_field = parts[2]
        ref = parts[3]
        alt_str = parts[4]
        info = parts[7] if len(parts) > 7 else ""

        alts = [a.strip() for a in alt_str.split(",")]

        gene = _parse_info_gene(info) or gene_at_position(chrom, pos)

        # Parse CNV from INFO (CYP2D6)
        cn_val = _parse_info_cn(info)
        if cn_val is not None and ("SVTYPE" in info.upper() or "GENE=CYP2D6" in info.upper()):
            result.cnv_by_gene["CYP2D6"] = CNVResult(
                gene="CYP2D6", copy_number=cn_val, confidence="explicit"
            )

        if not gene or gene not in result.variants_by_gene:
            continue

        rsid = _parse_info_rs(info) or _extract_rsid_from_id(id_field) or get_rsid_by_position(chrom, pos)
        genotype = None
        if len(parts) > 9:
            fmt = parts[8].split(":")
            gt_idx = fmt.index("GT") if "GT" in fmt else 0
            sample_parts = parts[9].split(":")
            if gt_idx < len(sample_parts):
                genotype = sample_parts[gt_idx].replace("|", "/")

        if rsid and rsid in PGX_VARIANTS:
            info_map = PGX_VARIANTS[rsid]
            result.variants_by_gene[gene].append(
                ParsedVariant(
                    rsid=rsid,
                    gene=gene,
                    allele=info_map["allele"],
                    function=info_map["function"],
                    chrom=chrom,
                    pos=pos,
                    ref=ref,
                    alt=alts[0] if alts else ".",
                    genotype=genotype,
                    source="info",
                )
            )
        else:
            result.variants_by_gene[gene].append(
                ParsedVariant(
                    rsid=rsid or f"{chrom}:{pos}",
                    gene=gene,
                    allele="?",
                    function="Unknown",
                    chrom=chrom,
                    pos=pos,
                    ref=ref,
                    alt=alts[0] if alts else ".",
                    genotype=genotype,
                    source="position",
                )
            )
            result.annotation_completeness = "partial"

    return result
