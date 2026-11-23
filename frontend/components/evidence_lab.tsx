"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AlertCircle, Download, FileCheck2, FlaskConical, Loader2, RefreshCw } from "lucide-react";
import { api, EvidenceAnnotationSummary } from "../lib/api";

function downloadText(filename: string, contents: string) {
  const url = URL.createObjectURL(new Blob([contents], { type: "application/x-ndjson;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function EvidenceLab() {
  const [summary, setSummary] = useState<EvidenceAnnotationSummary | null>(null);
  const [heldOutIds, setHeldOutIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextSummary = await api.getEvidenceAnnotationSummary();
      setSummary(nextSummary);
      setHeldOutIds((current) => current.filter((id) => nextSummary.documents.some((doc) => doc.document_id === id)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load annotation progress.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggleHeldOut = (documentId: string) => {
    setHeldOutIds((current) => current.includes(documentId)
      ? current.filter((id) => id !== documentId)
      : [...current, documentId]);
    setNotice(null);
  };

  const exportDatasets = async () => {
    if (!heldOutIds.length) return;
    setExporting(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.exportEvidenceDatasets(heldOutIds);
      downloadText("human_train.jsonl", result.train_jsonl);
      downloadText("human_test.jsonl", result.test_jsonl);
      setNotice(`Exported ${result.train_examples} training labels from ${result.train_documents} document(s) and ${result.test_examples} test labels from ${result.test_documents} held-out document(s).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not export labeled examples.");
    } finally {
      setExporting(false);
    }
  };

  return (
    <main className="flex-1 overflow-y-auto p-6 lg:p-8">
      <div className="mx-auto max-w-5xl space-y-6">
        <section className="rounded-2xl border border-indigo-500/20 bg-gradient-to-br from-indigo-950/60 via-slate-900/80 to-slate-900 p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-2xl">
              <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-3 py-1 text-[11px] font-medium text-indigo-300">
                <FlaskConical className="h-3.5 w-3.5" /> NEXUS MODEL WORKSHOP
              </div>
              <h2 className="text-2xl font-bold text-white">Teach NEXUS what good evidence looks like.</h2>
              <p className="mt-2 text-sm leading-relaxed text-slate-400">Review claim-to-passage pairs in Research Studio, then hold out entire documents here to create a more honest evaluation set for your verifier.</p>
            </div>
            <button onClick={() => void refresh()} disabled={loading} className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs text-slate-300 hover:border-indigo-500 disabled:opacity-50">
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh progress
            </button>
          </div>
          <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Metric label="Human labels" value={summary?.total ?? "—"} />
            <Metric label="Supports" value={summary?.labels.supports ?? "—"} tone="text-emerald-300" />
            <Metric label="Contradicts" value={summary?.labels.contradicts ?? "—"} tone="text-rose-300" />
            <Metric label="Insufficient" value={summary?.labels.insufficient ?? "—"} tone="text-amber-300" />
          </div>
        </section>

        <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-semibold text-slate-100">Choose whole documents to hold out</h3>
              <p className="mt-1 text-xs text-slate-500">All labels from checked documents go to the test set. Other documents become training data.</p>
            </div>
            <span className="rounded-full border border-slate-700 px-2.5 py-1 text-[10px] text-slate-400">{heldOutIds.length} held out</span>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 py-10 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> Loading labels…</div>
          ) : !summary?.documents.length ? (
            <div className="mt-5 rounded-xl border border-dashed border-slate-700 p-6 text-center">
              <FileCheck2 className="mx-auto h-7 w-7 text-slate-500" />
              <p className="mt-3 text-sm font-medium text-slate-300">No human-reviewed examples yet</p>
              <p className="mx-auto mt-1 max-w-lg text-xs leading-relaxed text-slate-500">Go to Research Studio, ask questions about several PDFs, then use the supports / contradicts / insufficient buttons under each claim’s cited passage. Review labels carefully.</p>
            </div>
          ) : (
            <div className="mt-4 divide-y divide-slate-800">
              {summary.documents.map((document) => (
                <label key={document.document_id} className="flex cursor-pointer items-center gap-3 py-3">
                  <input type="checkbox" checked={heldOutIds.includes(document.document_id)} onChange={() => toggleHeldOut(document.document_id)} className="h-4 w-4 rounded border-slate-600 bg-slate-950 text-indigo-500 focus:ring-indigo-500" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-slate-200">{document.filename}</span>
                    <span className="mt-1 block text-[10px] text-slate-500">{document.count} labels · {document.document_id}</span>
                  </span>
                  <span className="hidden gap-2 text-[10px] sm:flex">
                    <span className="text-emerald-300">S {document.labels.supports}</span>
                    <span className="text-rose-300">C {document.labels.contradicts}</span>
                    <span className="text-amber-300">I {document.labels.insufficient}</span>
                  </span>
                </label>
              ))}
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 pt-4">
            <p className="max-w-xl text-[11px] leading-relaxed text-slate-500">For a useful test, reserve multiple documents and make sure the remaining training documents cover all three labels. Do not use the held-out results to tune the model.</p>
            <button onClick={() => void exportDatasets()} disabled={exporting || loading || !summary?.total || heldOutIds.length === 0} className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-xs font-semibold text-white shadow-lg shadow-indigo-950/40 transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40">
              {exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              Export disjoint JSONL sets
            </button>
          </div>
        </section>

        {(error || notice) && (
          <div role={error ? "alert" : "status"} className={`flex items-start gap-2 rounded-xl border p-3 text-xs ${error ? "border-rose-800 bg-rose-950/30 text-rose-300" : "border-emerald-800 bg-emerald-950/30 text-emerald-300"}`}>
            {error ? <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /> : <FileCheck2 className="mt-0.5 h-4 w-4 shrink-0" />}
            <span>{error || notice}</span>
          </div>
        )}

        <section className="rounded-2xl border border-slate-800 bg-slate-950 p-5">
          <h3 className="text-sm font-semibold text-slate-200">Next: train and evaluate</h3>
          <p className="mt-1 text-xs text-slate-500">After exporting, run these from the backend directory. The external test checks document overlap before training.</p>
          <pre className="mt-3 overflow-x-auto rounded-xl border border-slate-800 bg-black/30 p-4 text-[11px] leading-relaxed text-indigo-200">{`.\\venv\\Scripts\\python.exe -m scripts.train_evidence_verifier --dataset data\\human_train.jsonl --test-dataset data\\human_test.jsonl --output models\\evidence_verifier.joblib`}</pre>
          <p className="mt-3 text-[10px] text-amber-300/80">Labels and exported passages may contain private document text. Keep the downloaded datasets secure and only use data you have permission to use for model development.</p>
        </section>
      </div>
    </main>
  );
}

function Metric({ label, value, tone = "text-white" }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <span className="text-[10px] text-slate-500">{label}</span>
      <div className={`mt-1 text-xl font-bold ${tone}`}>{value}</div>
    </div>
  );
}
