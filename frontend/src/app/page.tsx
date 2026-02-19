"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Upload,
  FileText,
  Pill,
  AlertCircle,
  ChevronDown,
  Check,
} from "lucide-react";

const SUPPORTED_DRUGS = [
  "Codeine",
  "Warfarin",
  "Clopidogrel",
  "Simvastatin",
  "Azathioprine",
  "Fluorouracil",
];

const MAX_FILE_SIZE = 5 * 1024 * 1024;

export default function UploadPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [drugs, setDrugs] = useState<string[]>(["Codeine"]);
  const [drugDropdownOpen, setDrugDropdownOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [dragActive, setDragActive] = useState(false);

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const f = e.dataTransfer.files[0];
    if (f) {
      if (f.size > MAX_FILE_SIZE) {
        setError("File exceeds 5MB limit. Please provide a smaller VCF file.");
      } else {
        setError(null);
        setFile(f);
      }
    }
  }, []);

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(e.type === "dragenter" || e.type === "dragover");
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) {
      if (f.size > MAX_FILE_SIZE) {
        setError("File exceeds 5MB limit. Please provide a smaller VCF file.");
      } else {
        setError(null);
        setFile(f);
      }
    }
  };

  const toggleDrug = (drug: string) => {
    setDrugs((prev) =>
      prev.includes(drug) ? prev.filter((d) => d !== drug) : [...prev, drug]
    );
  };

  const handleAnalyze = async () => {
    if (!file || drugs.length === 0) return;
    setError(null);
    setLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("drugs", drugs.map((d) => d.toUpperCase()).join(","));

      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "https://alpha-x-84p9.onrender.com";
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 120000);
      const res = await fetch(`${apiUrl}/analyze`, {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });
      clearTimeout(timeout);

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Analysis failed");
      }
      const data = await res.json();
      sessionStorage.setItem(`pharmaguard-${data.analysis_id}`, JSON.stringify(data));
      router.push(`/results/${data.analysis_id}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Analysis failed. Please try again.";
      if (msg.includes("5MB")) setError("File exceeds 5MB limit. Please provide a smaller VCF file.");
      else if (msg.includes("parse") || msg.includes("VCF")) setError("We couldn't parse this VCF file. Please ensure it's a valid VCF v4.2 format.");
      else if (msg.includes("support") || msg.includes("contact")) setError("Analysis failed. Please try again. If problem persists, contact support.");
      else if (msg.includes("fetch") || msg.includes("Failed") || msg.includes("abort")) setError("Failed to connect to server. The backend may be waking up (Render free tier)—please wait 1–2 minutes and try again.");
      else setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const isValid = file && drugs.length > 0 && !error;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-sky-600 flex items-center justify-center">
            <Pill className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-slate-900">PharmaGuard</h1>
            <p className="text-sm text-slate-500">Pharmacogenomics Clinical Decision Support</p>
          </div>
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-6 py-12">
        <div className="space-y-8">
          <div>
            <h2 className="text-lg font-medium text-slate-900 mb-2">Upload VCF File</h2>
            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              className={`border-2 border-dashed rounded-xl p-12 text-center transition-colors ${
                dragActive ? "border-sky-500 bg-sky-50" : "border-slate-300 bg-white"
              }`}
            >
              <input
                type="file"
                accept=".vcf,.vcf.gz,.vcf.bgz"
                onChange={handleFileChange}
                className="hidden"
                id="vcf-upload"
              />
              <label htmlFor="vcf-upload" className="cursor-pointer block">
                <Upload className="w-12 h-12 text-slate-400 mx-auto mb-3" />
                <p className="text-slate-600 font-medium">
                  {file ? file.name : "Drag and drop your VCF file here"}
                </p>
                {file && (
                  <p className="text-sm text-slate-500 mt-1">{formatSize(file.size)}</p>
                )}
                <p className="text-sm text-slate-400 mt-2">or click to browse (max 5MB)</p>
              </label>
            </div>
          </div>

          <div>
            <h2 className="text-lg font-medium text-slate-900 mb-3">Select Drugs to Analyze</h2>
            <div className="relative">
              <button
                type="button"
                onClick={() => setDrugDropdownOpen(!drugDropdownOpen)}
                className="w-full flex items-center justify-between px-4 py-3 bg-white border border-slate-300 rounded-lg hover:border-slate-400"
              >
                <span className="text-slate-700">
                  {drugs.length === 0
                    ? "Select drugs..."
                    : drugs.join(", ")}
                </span>
                <ChevronDown
                  className={`w-5 h-5 text-slate-500 transition-transform ${
                    drugDropdownOpen ? "rotate-180" : ""
                  }`}
                />
              </button>
              {drugDropdownOpen && (
                <div className="absolute z-10 mt-1 w-full bg-white border border-slate-200 rounded-lg shadow-lg py-1">
                  {SUPPORTED_DRUGS.map((drug) => (
                    <button
                      key={drug}
                      type="button"
                      onClick={() => toggleDrug(drug)}
                      className="w-full flex items-center gap-2 px-4 py-2 hover:bg-slate-50 text-left"
                    >
                      {drugs.includes(drug) ? (
                        <Check className="w-4 h-4 text-sky-600" />
                      ) : (
                        <span className="w-4" />
                      )}
                      {drug}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {error && (
            <div className="flex items-start gap-2 p-4 bg-red-50 border border-red-200 rounded-lg">
              <AlertCircle className="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
              <p className="text-sm text-red-800">{error}</p>
            </div>
          )}

          <button
            onClick={handleAnalyze}
            disabled={!isValid || loading}
            className="w-full py-3 px-6 bg-sky-600 text-white font-medium rounded-lg hover:bg-sky-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <span className="animate-spin rounded-full h-5 w-5 border-2 border-white border-t-transparent" />
                Analyzing...
              </>
            ) : (
              <>
                <FileText className="w-5 h-5" />
                Analyze
              </>
            )}
          </button>
        </div>

        <p className="mt-8 text-center text-sm text-slate-500">
          Supported: Codeine, Warfarin, Clopidogrel, Simvastatin, Azathioprine, Fluorouracil
        </p>
      </main>
    </div>
  );
}
