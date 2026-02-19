// Env var for Vercel; fallback to production backend (use .env.local with http://localhost:8000 for local dev)
const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "https://alpha-x-84p9.onrender.com";

export interface RiskAssessment {
  risk_label: "Safe" | "Adjust Dosage" | "Toxic" | "Ineffective" | "Unknown";
  confidence_score: number;
  severity: "none" | "low" | "moderate" | "high" | "critical";
  rationale?: string;
}

export interface ClinicalRecommendation {
  action: string;
  dose_adjustment?: string | null;
  monitoring?: string | null;
  alternative_drugs?: string[] | null;
}

export interface PharmacogenomicProfile {
  gene: string;
  diplotype: string;
  phenotype: string;
  detected_variants: string[];
  activity_score?: number | null;
  copy_number?: number | null;
}

export interface QualityMetrics {
  annotation_completeness: "full" | "partial" | "low";
  variants_analyzed: number;
  confidence_breakdown?: Record<string, number> | null;
  interaction_warning?: string | null;
}

export interface LLMExplanation {
  summary: string;
  mechanism: string;
  citation: string;
}

export interface DrugAnalysisResult {
  drug: string;
  pharmacogenomic_profile: PharmacogenomicProfile;
  risk_assessment: RiskAssessment;
  clinical_recommendation: ClinicalRecommendation;
  quality_metrics: QualityMetrics;
  llm_explanation?: LLMExplanation | null;
}

export interface UnsupportedDrugResult {
  drug: string;
  risk_assessment: RiskAssessment;
  clinical_recommendation: ClinicalRecommendation;
}

export interface AnalysisResponse {
  patient_id: string;
  analysis_id: string;
  timestamp: string;
  results: (DrugAnalysisResult | UnsupportedDrugResult)[];
  vcf_hash?: string | null;
  audit_id?: string | null;
}

export async function analyzeVcf(file: File, drugs: string): Promise<AnalysisResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("drugs", drugs);

  const res = await fetch(`${API_URL}/analyze`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Analysis failed");
  }
  return res.json();
}

export async function getSupportedDrugs(): Promise<string[]> {
  const res = await fetch(`${API_URL}/drugs`);
  const data = await res.json();
  return data.drugs || [];
}

export function isDrugResult(r: DrugAnalysisResult | UnsupportedDrugResult): r is DrugAnalysisResult {
  return "pharmacogenomic_profile" in r;
}

export async function getResults(analysisId: string): Promise<AnalysisResponse> {
  const res = await fetch(`${API_URL}/results/${analysisId}`);
  if (!res.ok) throw new Error("Analysis not found");
  return res.json();
}

export async function regenerateExplanation(
  analysisId: string,
  drug: string
): Promise<{ llm_explanation: LLMExplanation }> {
  const formData = new FormData();
  formData.append("analysis_id", analysisId);
  formData.append("drug", drug);
  const res = await fetch(`${API_URL}/regenerate-explanation`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error("Failed to regenerate");
  return res.json();
}
