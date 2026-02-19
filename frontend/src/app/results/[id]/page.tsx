"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  CheckCircle,
  Info,
  AlertTriangle,
  AlertCircle,
  Ban,
  Copy,
  Download,
  ChevronDown,
  ChevronUp,
  FileText,
  RefreshCw,
} from "lucide-react";
import { jsPDF } from "jspdf";
import type { AnalysisResponse } from "@/lib/api";
import { getResults, isDrugResult, regenerateExplanation } from "@/lib/api";

const RISK_COLORS: Record<string, string> = {
  Safe: "#10b981",
  "Adjust Dosage": "#f59e0b",
  Toxic: "#ef4444",
  Ineffective: "#ef4444",
  Unknown: "#6b7280",
};

const SEVERITY_ICONS: Record<string, React.ReactNode> = {
  none: <CheckCircle className="w-5 h-5" />,
  low: <Info className="w-5 h-5" />,
  moderate: <AlertTriangle className="w-5 h-5" />,
  high: <AlertCircle className="w-5 h-5" />,
  critical: <Ban className="w-5 h-5" />,
};

export default function ResultsPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [data, setData] = useState<AnalysisResponse | null>(null);
  const [expandedGenes, setExpandedGenes] = useState<Set<string>>(new Set());
  const [expandedLLM, setExpandedLLM] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState(false);
  const [regenerating, setRegenerating] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      const stored = sessionStorage.getItem(`pharmaguard-${id}`);
      if (stored) {
        try {
          setData(JSON.parse(stored));
          return;
        } catch {
          /* fall through to API */
        }
      }
      try {
        const fetched = await getResults(id);
        setData(fetched);
        sessionStorage.setItem(`pharmaguard-${id}`, JSON.stringify(fetched));
      } catch {
        setLoadError("Analysis not found");
      }
    };
    load();
  }, [id]);

  const handleRegenerate = async (drug: string) => {
    if (!data) return;
    setRegenerating(drug);
    try {
      const { llm_explanation } = await regenerateExplanation(data.analysis_id, drug);
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          results: prev.results.map((r) =>
            r.drug === drug && "llm_explanation" in r
              ? { ...r, llm_explanation }
              : r
          ),
        };
      });
      setExpandedLLM((prev) => new Set(Array.from(prev).concat(drug)));
    } catch {
      /* ignore */
    } finally {
      setRegenerating(null);
    }
  };

  const toggleGene = (gene: string) => {
    setExpandedGenes((prev) => {
      const next = new Set(prev);
      if (next.has(gene)) next.delete(gene);
      else next.add(gene);
      return next;
    });
  };

  const toggleLLM = (drug: string) => {
    setExpandedLLM((prev) => {
      const next = new Set(prev);
      if (next.has(drug)) next.delete(drug);
      else next.add(drug);
      return next;
    });
  };

  const copyJson = () => {
    if (data) {
      navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const downloadPdf = () => {
    if (!data) return;
    const doc = new jsPDF();
    doc.setFontSize(18);
    doc.text("PharmaGuard Clinical Report", 20, 20);
    doc.setFontSize(10);
    doc.text(`Patient ID: ${data.patient_id}`, 20, 30);
    doc.text(`Analysis ID: ${data.analysis_id}`, 20, 36);
    doc.text(`Date: ${data.timestamp}`, 20, 42);
    doc.text(`VCF Hash: ${data.vcf_hash || "N/A"}`, 20, 48);

    let y = 60;
    data.results.forEach((r) => {
      doc.setFontSize(12);
      doc.text(`Drug: ${r.drug}`, 20, y);
      y += 6;
      doc.text(`Risk: ${r.risk_assessment.risk_label}`, 20, y);
      y += 6;
      doc.text(`Confidence: ${(r.risk_assessment.confidence_score * 100).toFixed(0)}%`, 20, y);
      y += 6;
      doc.text(`Action: ${r.clinical_recommendation.action}`, 20, y);
      y += 10;
      if (isDrugResult(r) && r.pharmacogenomic_profile) {
        doc.text(`Gene: ${r.pharmacogenomic_profile.gene}`, 20, y);
        y += 6;
        doc.text(`Diplotype: ${r.pharmacogenomic_profile.diplotype}`, 20, y);
        y += 6;
        doc.text(`Phenotype: ${r.pharmacogenomic_profile.phenotype}`, 20, y);
        y += 10;
      }
    });
    doc.text(
      "Disclaimer: This report is for clinical decision support only. Always consult a qualified healthcare provider.",
      20,
      doc.internal.pageSize.height - 20,
      { maxWidth: 170 }
    );
    doc.save(`PharmaGuard-Report-${data.analysis_id}.pdf`);
  };

  if (loadError) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <p className="text-red-600">{loadError}</p>
        <button
          onClick={() => router.push("/")}
          className="px-4 py-2 bg-sky-600 text-white rounded-lg"
        >
          New Analysis
        </button>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-sky-600 border-t-transparent" />
      </div>
    );
  }

  const primaryResult = data.results[0];
  const primaryRisk = primaryResult?.risk_assessment?.risk_label || "Unknown";
  const bannerColor = RISK_COLORS[primaryRisk] || RISK_COLORS.Unknown;

  return (
    <div className="min-h-screen bg-slate-50">
      <div
        className="h-24 flex items-center justify-center text-white"
        style={{ backgroundColor: bannerColor }}
      >
        <div className="text-center">
          <h1 className="text-2xl font-bold">{primaryRisk}</h1>
          <p className="text-white/90 text-sm mt-1">
            {data.patient_id} • {new Date(data.timestamp).toLocaleString()}
          </p>
        </div>
      </div>

      <main className="max-w-4xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 rounded-full border-4 flex items-center justify-center"
              style={{ borderColor: bannerColor, color: bannerColor }}>
              <span className="text-2xl font-bold">
                {((primaryResult?.risk_assessment?.confidence_score ?? 0) * 100).toFixed(0)}%
              </span>
            </div>
            <div className="group relative">
              <p className="text-sm text-slate-500">Confidence</p>
              <p className="font-medium">{((primaryResult?.risk_assessment?.confidence_score ?? 0) * 100).toFixed(0)}%</p>
              {isDrugResult(primaryResult) && primaryResult.quality_metrics?.confidence_breakdown && (
                <div className="absolute left-0 top-full mt-1 hidden group-hover:block z-10 p-3 bg-white border shadow-lg rounded-lg text-xs min-w-[200px]">
                  <p className="font-medium mb-2">Confidence breakdown</p>
                  {Object.entries(primaryResult.quality_metrics.confidence_breakdown).map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-4">
                      <span>{k.replace(/_/g, " ")}</span>
                      <span>{(v * 100).toFixed(0)}%</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={copyJson}
              className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 rounded-lg hover:bg-slate-50"
            >
              <Copy className="w-4 h-4" />
              {copied ? "Copied!" : "Copy JSON"}
            </button>
            <button
              onClick={downloadPdf}
              className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 rounded-lg hover:bg-slate-50"
            >
              <Download className="w-4 h-4" />
              PDF Report
            </button>
            <a
              href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/audit/export`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 rounded-lg hover:bg-slate-50"
            >
              <Download className="w-4 h-4" />
              Audit CSV
            </a>
            <button
              onClick={() => router.push("/")}
              className="flex items-center gap-2 px-4 py-2 bg-sky-600 text-white rounded-lg hover:bg-sky-700"
            >
              <FileText className="w-4 h-4" />
              New Analysis
            </button>
          </div>
        </div>

        <div className="space-y-6">
          {data.results.map((result) => (
            <div key={result.drug} className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <div className="p-6 border-b border-slate-100">
                <div className="flex items-start justify-between">
                  <div>
                    <h2 className="text-lg font-semibold text-slate-900">{result.drug}</h2>
                    <div className="flex items-center gap-2 mt-1">
                      <span
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-sm font-medium text-white"
                        style={{ backgroundColor: RISK_COLORS[result.risk_assessment.risk_label] }}
                      >
                        {SEVERITY_ICONS[result.risk_assessment.severity]}
                        {result.risk_assessment.risk_label}
                      </span>
                      <span className="text-sm text-slate-500">
                        Confidence: {(result.risk_assessment.confidence_score * 100).toFixed(0)}%
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {isDrugResult(result) ? (
                <>
                  {result.pharmacogenomic_profile && (
                    <div className="p-6 border-b border-slate-100">
                      <h3 className="font-medium text-slate-900 mb-3">Gene Profile</h3>
                      <div className="grid gap-3">
                        <div className="flex justify-between">
                          <span className="text-slate-500">Gene</span>
                          <span className="font-medium">{result.pharmacogenomic_profile.gene}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Diplotype</span>
                          <span className="font-medium" title="Star allele genotype">
                            {result.pharmacogenomic_profile.diplotype}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-500">Phenotype</span>
                          <span className="font-medium">{result.pharmacogenomic_profile.phenotype}</span>
                        </div>
                        {result.pharmacogenomic_profile.detected_variants?.length > 0 && (
                          <div>
                            <button
                              onClick={() => toggleGene(result.drug)}
                              className="flex items-center gap-2 text-sky-600 text-sm"
                            >
                              {expandedGenes.has(result.drug) ? (
                                <ChevronUp className="w-4 h-4" />
                              ) : (
                                <ChevronDown className="w-4 h-4" />
                              )}
                              Detected Variants ({result.pharmacogenomic_profile.detected_variants.length})
                            </button>
                            {expandedGenes.has(result.drug) && (
                              <ul className="mt-2 pl-4 list-disc text-sm text-slate-600">
                                {result.pharmacogenomic_profile.detected_variants.map((v) => (
                                  <li key={v}>{v}</li>
                                ))}
                              </ul>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  <div className="p-6 border-b border-slate-100">
                    <h3 className="font-medium text-slate-900 mb-3">Clinical Recommendation</h3>
                    <p className="font-semibold text-slate-800">{result.clinical_recommendation.action}</p>
                    {result.clinical_recommendation.dose_adjustment && (
                      <p className="text-slate-600 mt-1">Dose: {result.clinical_recommendation.dose_adjustment}</p>
                    )}
                    {result.clinical_recommendation.monitoring && (
                      <p className="text-slate-600 mt-1">Monitoring: {result.clinical_recommendation.monitoring}</p>
                    )}
                    {result.clinical_recommendation.alternative_drugs?.length && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {result.clinical_recommendation.alternative_drugs.map((alt) => (
                          <span
                            key={alt}
                            className="px-3 py-1 bg-slate-100 rounded-full text-sm"
                          >
                            {alt}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {result.llm_explanation && (
                    <div className="p-6">
                      <button
                        onClick={() => toggleLLM(result.drug)}
                        className="flex items-center gap-2 font-medium text-slate-900"
                      >
                        {expandedLLM.has(result.drug) ? (
                          <ChevronUp className="w-4 h-4" />
                        ) : (
                          <ChevronDown className="w-4 h-4" />
                        )}
                        AI Explanation
                      </button>
                      {expandedLLM.has(result.drug) && (
                        <div className="mt-3 p-4 bg-slate-50 rounded-lg text-sm space-y-2">
                          <p><strong>Summary:</strong> {result.llm_explanation.summary}</p>
                          <p><strong>Mechanism:</strong> {result.llm_explanation.mechanism}</p>
                          <p className="text-slate-500 text-xs">{result.llm_explanation.citation}</p>
                          <button
                            onClick={() => handleRegenerate(result.drug)}
                            disabled={regenerating === result.drug}
                            className="mt-2 flex items-center gap-2 text-sky-600 hover:text-sky-700 text-xs"
                          >
                            <RefreshCw className={`w-4 h-4 ${regenerating === result.drug ? "animate-spin" : ""}`} />
                            {regenerating === result.drug ? "Regenerating..." : "Regenerate"}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </>
              ) : (
                <div className="p-6">
                  <p className="text-slate-600">{result.clinical_recommendation.action}</p>
                  <p className="text-slate-500 text-sm mt-2">
                    Supported drugs: Codeine, Warfarin, Clopidogrel, Simvastatin, Azathioprine, Fluorouracil
                  </p>
                </div>
              )}
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
