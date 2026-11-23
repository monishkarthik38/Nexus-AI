"use client";

import React, { useState, useEffect, useCallback } from "react";
import { Uploader } from "@/components/uploader";
import { DocumentList } from "@/components/document_list";
import { ChatBox } from "@/components/chat_box";
import { EvidenceLab } from "@/components/evidence_lab";
import { DossierStudio } from "@/components/dossier_studio";
import { api, auth, AUTH_MODE, DocumentItem, type HealthStatus } from "@/lib/api";
import { SignIn } from "@/components/sign_in";
import { Database, Activity, Play, Layers } from "lucide-react";

interface EvaluationMetricSet {
  citation_precision: number;
  abstention_accuracy: number;
  prompt_injection_defense: number;
  average_latency_ms: number;
}

interface EvaluationDetail {
  id: string;
  category: string;
  answer_preview: string;
  latency_ms: number;
  citations_count: number;
  has_knowledge_gap: boolean;
}

interface EvaluationResult {
  metrics: EvaluationMetricSet;
  details: EvaluationDetail[];
}

export default function NexusDashboard() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [healthStatus, setHealthStatus] = useState<HealthStatus | null>(null);
  const [activeTab, setActiveTab] = useState<"research" | "dossiers" | "evaluation" | "evidence-lab">("research");
  const [evaluating, setEvaluating] = useState(false);
  const [evalResult, setEvalResult] = useState<EvaluationResult | null>(null);
  const [authReady, setAuthReady] = useState(AUTH_MODE === "development");
  const [isAuthenticated, setIsAuthenticated] = useState(AUTH_MODE === "development");

  const loadDocuments = useCallback(async () => {
    try {
      const docs = await api.getDocuments();
      setDocuments(docs);
    } catch (error) {
      console.error("Failed to load documents", error);
    }
  }, []);

  const loadHealth = useCallback(async () => {
    try {
      const h = await api.getHealth();
      setHealthStatus(h);
    } catch (error) {
      console.error("Failed to load health", error);
    }
  }, []);

  useEffect(() => {
    if (AUTH_MODE === "development") return;
    let active = true;
    void auth.getSession().then((session) => {
      if (active) {
        setIsAuthenticated(Boolean(session));
        setAuthReady(true);
      }
    }).catch(() => {
      if (active) setAuthReady(true);
    });
    const subscription = auth.onChange((session) => {
      setIsAuthenticated(Boolean(session));
      setAuthReady(true);
      setDocuments([]);
      setSelectedDocIds([]);
    });
    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    void loadDocuments();
    void loadHealth();
  }, [isAuthenticated, loadDocuments, loadHealth]);

  const hasProcessingDocuments = documents.some((document) => document.status === "processing");
  useEffect(() => {
    if (!isAuthenticated || !hasProcessingDocuments) return;
    const interval = window.setInterval(() => void loadDocuments(), 2500);
    return () => window.clearInterval(interval);
  }, [hasProcessingDocuments, isAuthenticated, loadDocuments]);

  if (!authReady) {
    return <div className="flex min-h-screen items-center justify-center bg-slate-950 text-sm text-slate-400">Checking secure session…</div>;
  }
  if (!isAuthenticated) {
    return <SignIn onAuthenticated={() => setIsAuthenticated(true)} />;
  }

  const handleToggleSelect = (id: string) => {
    setSelectedDocIds((prev) =>
      prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]
    );
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deleteDocument(id);
      setDocuments((prev) => prev.filter((d) => d.id !== id));
      setSelectedDocIds((prev) => prev.filter((d) => d !== id));
    } catch {
      alert("Failed to delete document");
    }
  };

  const handleRunEvaluation = async () => {
    setEvaluating(true);
    setEvalResult(null);
    try {
      const res = await api.runEvaluation(selectedDocIds.length > 0 ? selectedDocIds : undefined) as EvaluationResult;
      setEvalResult(res);
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Evaluation request failed.";
      alert(`Evaluation failed: ${message}`);
    } finally {
      setEvaluating(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-slate-950 text-slate-100 lg:h-dvh lg:min-h-0 lg:overflow-hidden">
      {/* Top Navbar */}
      <header className="sticky top-0 z-20 flex shrink-0 flex-col gap-3 border-b border-slate-800 bg-slate-900/95 px-4 py-3 backdrop-blur-md sm:px-6 lg:h-16 lg:flex-row lg:items-center lg:justify-between lg:gap-4 lg:py-0">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center font-bold text-white shadow-lg shadow-indigo-500/20">
            N
          </div>
          <div>
            <h1 className="text-base font-bold tracking-tight bg-gradient-to-r from-white via-slate-200 to-indigo-300 bg-clip-text text-transparent">
              NEXUS AI
            </h1>
          </div>
          <span className="hidden text-xs px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-medium sm:inline-flex">
            Agentic Knowledge Platform
          </span>
        </div>

        {/* Tab switch & Health badge */}
        <div className="flex min-w-0 items-center justify-between gap-3 lg:justify-end lg:gap-4">
          <nav aria-label="Workspace sections" className="flex min-w-0 max-w-full overflow-x-auto rounded-lg bg-slate-900 border border-slate-800 p-0.5 text-xs">
            <button
              aria-current={activeTab === "research" ? "page" : undefined}
              onClick={() => setActiveTab("research")}
              className={`shrink-0 px-3 py-1.5 rounded-md font-medium transition-all ${
                activeTab === "research"
                  ? "bg-indigo-600 text-white shadow"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Research Studio
            </button>
            <button
              aria-current={activeTab === "dossiers" ? "page" : undefined}
              onClick={() => setActiveTab("dossiers")}
              className={`shrink-0 px-3 py-1.5 rounded-md font-medium transition-all ${
                activeTab === "dossiers"
                  ? "bg-indigo-600 text-white shadow"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Deep Research
            </button>
            <button
              aria-current={activeTab === "evaluation" ? "page" : undefined}
              onClick={() => setActiveTab("evaluation")}
              className={`shrink-0 px-3 py-1.5 rounded-md font-medium transition-all ${
                activeTab === "evaluation"
                  ? "bg-indigo-600 text-white shadow"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Evaluation Benchmark
            </button>
            <button
              aria-current={activeTab === "evidence-lab" ? "page" : undefined}
              onClick={() => setActiveTab("evidence-lab")}
              className={`shrink-0 px-3 py-1.5 rounded-md font-medium transition-all ${
                activeTab === "evidence-lab"
                  ? "bg-indigo-600 text-white shadow"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Evidence Lab
            </button>
          </nav>

          {healthStatus && (
            <div className="hidden shrink-0 items-center space-x-1.5 text-xs text-emerald-400 bg-emerald-950/40 border border-emerald-800/60 px-2.5 py-1 rounded-full sm:flex">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>{healthStatus.status}</span>
            </div>
          )}
          {AUTH_MODE !== "development" && (
            <button onClick={() => void auth.signOut()} className="shrink-0 rounded-lg border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:text-white">Sign out</button>
          )}
        </div>
      </header>

      {/* Main Content Area */}
      {activeTab === "research" ? (
        <main className="grid flex-1 grid-cols-1 gap-4 overflow-y-auto p-4 sm:gap-5 sm:p-5 lg:min-h-0 lg:grid-cols-12 lg:gap-6 lg:overflow-hidden lg:p-6">
          {/* Left Column: Document Ingestion & Scope */}
          <div className="min-w-0 space-y-4 lg:col-span-4 lg:flex lg:min-h-0 lg:flex-col lg:space-y-5 lg:overflow-hidden">
            <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-5 backdrop-blur-md">
              <h2 className="text-sm font-semibold text-slate-200 mb-3 flex items-center gap-2">
                <Layers className="w-4 h-4 text-indigo-400" />
                <span>Upload Research PDFs</span>
              </h2>
              <Uploader onUploadSuccess={() => loadDocuments()} />
            </div>

            <div className="flex min-h-[320px] flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/40 p-5 backdrop-blur-md lg:min-h-0 lg:flex-1">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
                  <Database className="w-4 h-4 text-indigo-400" />
                  <span>Document Library ({documents.length})</span>
                </h2>
                {selectedDocIds.length > 0 && (
                  <button
                    onClick={() => setSelectedDocIds([])}
                    className="text-xs text-indigo-400 hover:underline"
                  >
                    Clear selection
                  </button>
                )}
              </div>
              <p className="text-xs text-slate-500 mb-3">
                Check documents to scope queries, or uncheck all to search the entire library.
              </p>
              <div className="flex-1 overflow-y-auto">
                <DocumentList
                  documents={documents}
                  selectedDocIds={selectedDocIds}
                  onToggleSelect={handleToggleSelect}
                  onDeleteDoc={handleDelete}
                />
              </div>
            </div>
          </div>

          {/* Right Column: Agentic Chat & Research */}
          <div className="h-[72dvh] min-h-[480px] min-w-0 lg:col-span-8 lg:flex lg:h-auto lg:min-h-0 lg:flex-col lg:overflow-hidden">
            <ChatBox selectedDocIds={selectedDocIds} />
          </div>
        </main>
      ) : activeTab === "dossiers" ? (
        <DossierStudio documents={documents} selectedDocIds={selectedDocIds} />
      ) : activeTab === "evaluation" ? (
        /* Evaluation Benchmark Studio */
        <main className="flex-1 p-8 overflow-y-auto max-w-5xl mx-auto w-full">
          <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-6 backdrop-blur-md mb-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
                  <Activity className="w-5 h-5 text-indigo-400" />
                  <span>RAGAS & System Benchmark Evaluation</span>
                </h2>
                <p className="text-xs text-slate-400 mt-1">
                  Tests citation precision, unanswerable abstention accuracy, prompt injection defense, and retrieval recall across the benchmark dataset.
                </p>
              </div>

              <button
                onClick={handleRunEvaluation}
                disabled={evaluating}
                className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-lg shadow-indigo-500/20 disabled:opacity-50 transition-all"
              >
                {evaluating ? (
                  <>
                    <Activity className="w-4 h-4 animate-spin" />
                    <span>Executing Test Suite...</span>
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 fill-current" />
                    <span>Run Benchmark</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {evalResult && (
            <div className="space-y-6">
              {/* Metric Cards */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl">
                  <span className="text-xs text-slate-400 font-medium">Citation Precision</span>
                  <div className="text-2xl font-bold text-emerald-400 mt-1">
                    {(evalResult.metrics.citation_precision * 100).toFixed(0)}%
                  </div>
                  <span className="text-[10px] text-slate-500">Goal: 100% verified</span>
                </div>

                <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl">
                  <span className="text-xs text-slate-400 font-medium">Abstention Accuracy</span>
                  <div className="text-2xl font-bold text-indigo-400 mt-1">
                    {(evalResult.metrics.abstention_accuracy * 100).toFixed(0)}%
                  </div>
                  <span className="text-[10px] text-slate-500">Identifies knowledge gaps</span>
                </div>

                <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl">
                  <span className="text-xs text-slate-400 font-medium">Injection Defense</span>
                  <div className="text-2xl font-bold text-violet-400 mt-1">
                    {(evalResult.metrics.prompt_injection_defense * 100).toFixed(0)}%
                  </div>
                  <span className="text-[10px] text-slate-500">Guards against jailbreaks</span>
                </div>

                <div className="bg-slate-900/60 border border-slate-800 p-4 rounded-xl">
                  <span className="text-xs text-slate-400 font-medium">Avg Latency</span>
                  <div className="text-2xl font-bold text-slate-200 mt-1">
                    {evalResult.metrics.average_latency_ms} ms
                  </div>
                  <span className="text-[10px] text-slate-500">End-to-end response</span>
                </div>
              </div>

              {/* Benchmark Results Table */}
              <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
                <div className="px-5 py-3 border-b border-slate-800 text-xs font-semibold text-slate-300">
                  Detailed Test Case Results
                </div>
                <div className="divide-y divide-slate-800 text-xs">
                  {evalResult.details.map((t: EvaluationDetail) => (
                    <div key={t.id} className="p-4 flex items-center justify-between hover:bg-slate-850/50">
                      <div className="space-y-1 max-w-lg">
                        <div className="flex items-center space-x-2">
                          <span className="font-mono text-indigo-400">{t.id}</span>
                          <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">
                            {t.category}
                          </span>
                          {t.has_knowledge_gap && (
                            <span className="px-2 py-0.5 rounded bg-amber-950 text-amber-300 text-[10px] border border-amber-800">
                              Abstained (Knowledge Gap)
                            </span>
                          )}
                        </div>
                        <p className="text-slate-400 truncate">{t.answer_preview}</p>
                      </div>

                      <div className="text-right text-slate-500">
                        <div>{t.latency_ms} ms</div>
                        <div>{t.citations_count} citations</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </main>
      ) : (
        <EvidenceLab />
      )}
    </div>
  );
}
