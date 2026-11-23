"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, BookOpen, Download, FileText, Loader2, Sparkles } from "lucide-react";
import { api, DocumentItem, ResearchReport, ResearchReportSummary } from "@/lib/api";

interface DossierStudioProps {
  documents: DocumentItem[];
  selectedDocIds: string[];
}

export function DossierStudio({ documents, selectedDocIds }: DossierStudioProps) {
  const readyDocuments = useMemo(
    () => documents.filter((document) => document.status === "ready"),
    [documents]
  );
  const [topic, setTopic] = useState("");
  const [reportType, setReportType] = useState<"executive_dossier" | "study_guide">("executive_dossier");
  const [documentIds, setDocumentIds] = useState<string[]>(selectedDocIds);
  const [reports, setReports] = useState<ResearchReportSummary[]>([]);
  const [activeReport, setActiveReport] = useState<ResearchReport | null>(null);
  const [generating, setGenerating] = useState(false);
  const [loadingReportId, setLoadingReportId] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadReports = useCallback(async () => {
    try {
      setReports(await api.getResearchReports());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load saved dossiers.");
    }
  }, []);

  useEffect(() => {
    setDocumentIds(selectedDocIds.filter((id) => readyDocuments.some((document) => document.id === id)));
  }, [readyDocuments, selectedDocIds]);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  const toggleDocument = (id: string) => {
    setDocumentIds((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id]
    );
  };

  const handleGenerate = async (event: React.FormEvent) => {
    event.preventDefault();
    const cleanTopic = topic.trim() || "Complete experiment-by-experiment study guide";
    if ((reportType === "executive_dossier" && !topic.trim()) || documentIds.length === 0 || generating) return;

    setGenerating(true);
    setError(null);
    setActiveReport(null);
    try {
      const report = await api.createResearchReport(cleanTopic, documentIds, reportType);
      setActiveReport(report);
      setTopic("");
      await loadReports();
    } catch (generateError) {
      setError(generateError instanceof Error ? generateError.message : "Dossier generation failed.");
    } finally {
      setGenerating(false);
    }
  };

  const handleOpenReport = async (id: string) => {
    setLoadingReportId(id);
    setError(null);
    try {
      setActiveReport(await api.getResearchReport(id));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not open this dossier.");
    } finally {
      setLoadingReportId(null);
    }
  };

  const handleDownload = async () => {
    if (!activeReport || downloading) return;
    setDownloading(true);
    setError(null);
    try {
      const blob = await api.downloadResearchReportPdf(activeReport.id);
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `research-dossier-${activeReport.id}.pdf`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : "Could not download the PDF.");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <main className="flex-1 min-h-0 grid grid-cols-12 gap-6 p-6 overflow-hidden">
      <aside className="col-span-12 lg:col-span-4 flex flex-col gap-5 overflow-y-auto">
        <form onSubmit={handleGenerate} className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-4 flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-indigo-400" />
            <h2 className="text-sm font-semibold text-slate-100">Create a research document</h2>
          </div>
          <div className="mb-4 grid grid-cols-2 gap-2 rounded-xl border border-slate-800 bg-slate-950/50 p-1">
            <button type="button" onClick={() => setReportType("executive_dossier")} className={`rounded-lg px-2 py-2 text-[11px] font-medium ${reportType === "executive_dossier" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white"}`}>
              Executive dossier
            </button>
            <button type="button" onClick={() => setReportType("study_guide")} className={`rounded-lg px-2 py-2 text-[11px] font-medium ${reportType === "study_guide" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white"}`}>
              Experiment study guide
            </button>
          </div>
          <label htmlFor="dossier-topic" className="mb-2 block text-xs font-medium text-slate-300">
            {reportType === "study_guide" ? "Optional focus or output language" : "Research topic or decision question"}
          </label>
          <textarea
            id="dossier-topic"
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            maxLength={500}
            rows={4}
            placeholder={reportType === "study_guide" ? "e.g. Explain each experiment clearly in Hindi" : "e.g. Strategic risks and opportunities in the proposed expansion"}
            className="w-full resize-y rounded-xl border border-slate-700 bg-slate-950/70 p-3 text-sm text-slate-100 outline-none placeholder:text-slate-600 focus:border-indigo-500"
            required={reportType === "executive_dossier"}
          />
          <div className="mb-4 mt-1 text-right text-[10px] text-slate-500">{topic.length}/500</div>

          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-semibold text-slate-300">Evidence scope</h3>
            <span className="text-[10px] text-slate-500">{documentIds.length} selected</span>
          </div>
          <div className="max-h-52 space-y-1 overflow-y-auto rounded-xl border border-slate-800 bg-slate-950/40 p-2">
            {readyDocuments.length === 0 ? (
              <p className="p-2 text-xs text-slate-500">Upload and index documents before generating a dossier.</p>
            ) : readyDocuments.map((document) => (
              <label key={document.id} className="flex cursor-pointer items-start gap-2 rounded-lg p-2 text-xs text-slate-300 hover:bg-slate-800/70">
                <input
                  type="checkbox"
                  checked={documentIds.includes(document.id)}
                  onChange={() => toggleDocument(document.id)}
                  className="mt-0.5 accent-indigo-500"
                />
                <span className="break-all">{document.filename}</span>
              </label>
            ))}
          </div>
          <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
            {reportType === "study_guide"
              ? "Uses every detected experiment in order. AI explanations beyond the PDF are labeled separately; PDF facts keep page citations."
              : "Reports are grounded only in selected documents. Unsupported sections are marked as evidence gaps."}
          </p>
          <button
            type="submit"
            disabled={generating || (reportType === "executive_dossier" && !topic.trim()) || documentIds.length === 0}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-xs font-semibold text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {generating
              ? reportType === "study_guide" ? "Explaining each experiment..." : "Researching sources and drafting..."
              : reportType === "study_guide" ? "Generate study guide" : "Generate dossier"}
          </button>
        </form>

        <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
          <div className="mb-3 flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-indigo-400" />
            <h2 className="text-sm font-semibold text-slate-100">Saved dossiers</h2>
          </div>
          {reports.length === 0 ? (
            <p className="text-xs text-slate-500">Generated dossiers will appear here.</p>
          ) : (
            <div className="max-h-72 space-y-2 overflow-y-auto">
              {reports.map((report) => (
                <button
                  key={report.id}
                  type="button"
                  onClick={() => void handleOpenReport(report.id)}
                  disabled={loadingReportId === report.id}
                  className={`w-full rounded-xl border p-3 text-left transition-colors ${
                    activeReport?.id === report.id
                      ? "border-indigo-500/60 bg-indigo-950/40"
                      : "border-slate-800 bg-slate-950/40 hover:border-slate-700"
                  }`}
                >
                  <span className="flex items-start gap-2">
                    <FileText className="mt-0.5 h-4 w-4 shrink-0 text-indigo-400" />
                    <span className="min-w-0">
                      <span className="block truncate text-xs font-medium text-slate-200">{report.title}</span>
                      <span className="mt-1 block text-[10px] text-slate-500">
                        {new Date(report.created_at).toLocaleDateString()} · {report.citation_count} verified sources
                      </span>
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>
      </aside>

      <section className="col-span-12 flex min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/40 lg:col-span-8">
        {error && (
          <div role="alert" className="m-4 flex items-start gap-2 rounded-xl border border-rose-900/70 bg-rose-950/40 p-3 text-xs text-rose-200">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {generating ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
            <Loader2 className="h-8 w-8 animate-spin text-indigo-400" />
            <h2 className="text-sm font-semibold text-slate-200">{reportType === "study_guide" ? "Building your experiment-by-experiment study guide" : "Building your research dossier"}</h2>
            <p className="max-w-md text-xs leading-relaxed text-slate-500">
              {reportType === "study_guide"
                ? "NEXUS is explaining each experiment in order, separating general AI teaching notes from facts in your PDF."
                : "NEXUS is researching six executive report sections against the selected documents and verifying every citation."}
            </p>
          </div>
        ) : activeReport ? (
          <>
            <header className="flex items-center justify-between gap-4 border-b border-slate-800 bg-slate-900/60 px-5 py-4">
              <div className="min-w-0">
                <h2 className="truncate text-sm font-bold text-slate-100">{activeReport.title}</h2>
                <p className="mt-1 text-xs text-slate-500">
                  {activeReport.document_names.length} source documents · {activeReport.sections.reduce((sum, section) => sum + section.citations.length, 0)} citation links
                </p>
              </div>
              <button
                type="button"
                onClick={() => void handleDownload()}
                disabled={downloading}
                className="flex shrink-0 items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-xs font-medium text-slate-200 hover:border-indigo-500 hover:text-white disabled:opacity-50"
              >
                {downloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                Download PDF
              </button>
            </header>
            <div className="flex-1 overflow-y-auto p-5">
              <div className="mb-5 rounded-xl border border-indigo-900/50 bg-indigo-950/20 p-4">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-indigo-300">{activeReport.report_type === "study_guide" ? "Study guide focus / output language" : "Research question"}</div>
                <p className="mt-2 text-sm leading-relaxed text-slate-200">{activeReport.topic}</p>
                <p className="mt-3 text-[10px] text-slate-500">
                  Evidence scope: {activeReport.document_names.join(", ")}
                </p>
              </div>
              <div className="space-y-4">
                {activeReport.sections.map((section) => (
                  <article key={section.section_id} className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-sm font-semibold text-slate-100">{section.title}</h3>
                      {section.has_knowledge_gap && (
                        <span className="rounded-full border border-amber-800/70 bg-amber-950/50 px-2 py-1 text-[10px] text-amber-200">
                          Evidence gap
                        </span>
                      )}
                    </div>
                    <div className="mt-3 space-y-2 text-xs leading-relaxed text-slate-300">
                      {section.content.split(/\r?\n/).map((line, lineIndex) => {
                        const trimmed = line.trim();
                        const heading = trimmed.match(/^#{1,3}\s+(.+)$/);
                        const bullet = trimmed.match(/^[-*]\s+(.+)$/);
                        const numbered = trimmed.match(/^(\d+[.)])\s+(.+)$/);
                        const content = trimmed.replace(/\*\*/g, "");
                        if (!trimmed) return <div key={`${section.section_id}-${lineIndex}`} className="h-1" />;
                        if (heading) return <h4 key={`${section.section_id}-${lineIndex}`} className="pt-2 text-xs font-semibold text-slate-100">{heading[1]}</h4>;
                        if (bullet) return <p key={`${section.section_id}-${lineIndex}`} className="pl-3 before:mr-2 before:text-indigo-400 before:content-['•']">{bullet[1]}</p>;
                        if (numbered) return <p key={`${section.section_id}-${lineIndex}`} className="pl-3"><span className="mr-2 font-semibold text-indigo-300">{numbered[1]}</span>{numbered[2]}</p>;
                        return <p key={`${section.section_id}-${lineIndex}`}>{content}</p>;
                      })}
                    </div>
                    {section.citations.length > 0 && (
                      <div className="mt-4 border-t border-slate-800 pt-3">
                        <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Verified sources</div>
                        <div className="space-y-2">
                          {section.citations.map((citation) => (
                            <div key={`${section.section_id}:${citation.source_id}`} className="rounded-lg bg-slate-900/70 p-2.5">
                              <div className="text-[10px] font-medium text-indigo-300">
                                {citation.document_name} · Page {citation.page_number}
                              </div>
                              <p className="mt-1 text-[10px] leading-relaxed text-slate-500">{citation.excerpt}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </article>
                ))}
              </div>
            </div>
          </>
        ) : (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-slate-700 bg-slate-800/60">
              <FileText className="h-6 w-6 text-indigo-400" />
            </div>
            <h2 className="text-sm font-semibold text-slate-200">Executive dossiers and experiment study guides</h2>
            <p className="max-w-md text-xs leading-relaxed text-slate-500">
              Choose a report type and source documents. Create a decision-ready dossier or a clear study guide covering each experiment in your question bank.
            </p>
          </div>
        )}
      </section>
    </main>
  );
}
