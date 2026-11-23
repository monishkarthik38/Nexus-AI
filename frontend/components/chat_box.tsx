"use client";

import React, { useState, useRef, useEffect } from "react";
import { Send, Bot, User, AlertCircle, Sparkles, Loader2, RotateCcw } from "lucide-react";
import { api, ChatResponse, Citation, EvidenceClaim, EvidenceLabel } from "../lib/api";
import { CitationCard } from "./citation_card";
import { AgentStatus } from "./agent_status";

interface ChatBoxProps {
  selectedDocIds: string[];
}

interface MessageItem {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  claims?: EvidenceClaim[];
  has_knowledge_gap?: boolean;
  activity_logs?: string[];
}

export function ChatBox({ selectedDocIds }: ChatBoxProps) {
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [currentLogs, setCurrentLogs] = useState<string[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const [annotationStatus, setAnnotationStatus] = useState<Record<string, string>>({});
  const [annotationError, setAnnotationError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, currentLogs]);

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanQ = query.trim();
    if (!cleanQ || isLoading) return;

    const userMsgId = Date.now().toString();
    const newMsg: MessageItem = {
      id: userMsgId,
      role: "user",
      content: cleanQ,
    };

    setMessages((prev) => [...prev, newMsg]);
    setQuery("");
    setIsLoading(true);
    setCurrentLogs(["Initiating LangGraph agent workflow"]);

    try {
      const resp: ChatResponse = await api.sendChat(cleanQ, conversationId, selectedDocIds);
      setConversationId(resp.conversation_id);
      setCurrentLogs(resp.activity_logs);

      const assistantMsg: MessageItem = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: resp.answer,
        citations: resp.citations,
        claims: resp.claims,
        has_knowledge_gap: resp.has_knowledge_gap,
        activity_logs: resp.activity_logs,
      };

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (error: unknown) {
      const errorMsg: MessageItem = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: `Error: ${error instanceof Error ? error.message : "Unable to reach research agent."}`,
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClearHistory = () => {
    setMessages([]);
    setConversationId(undefined);
    setCurrentLogs([]);
  };

  const handleEvidenceLabel = async (claim: string, sourceId: string, label: EvidenceLabel) => {
    const key = `${sourceId}:${claim}`;
    setAnnotationError(null);
    setAnnotationStatus((current) => ({ ...current, [key]: "Saving…" }));
    try {
      await api.submitEvidenceLabel(sourceId, claim, label);
      setAnnotationStatus((current) => ({ ...current, [key]: `Saved: ${label}` }));
    } catch (error) {
      setAnnotationStatus((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      setAnnotationError(error instanceof Error ? error.message : "Could not save label.");
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-900/40 rounded-2xl border border-slate-800 backdrop-blur-md overflow-hidden">
      {/* Header */}
      <div className="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between bg-slate-900/60">
        <div className="flex items-center space-x-2">
          <div className="w-8 h-8 rounded-lg bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
            <Bot className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-slate-100 flex items-center gap-1.5">
              <span>Agentic Research Assistant</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-950 border border-indigo-800 text-indigo-300 uppercase tracking-wider font-mono">
                LangGraph + Qdrant
              </span>
            </h2>
            <p className="text-xs text-slate-500">
              {selectedDocIds.length === 0
                ? "Searching across all indexed documents"
                : `Scoped to ${selectedDocIds.length} selected document(s)`}
            </p>
          </div>
        </div>

        {messages.length > 0 && (
          <button
            onClick={handleClearHistory}
            title="Reset conversation"
            className="flex items-center space-x-1 text-xs text-slate-400 hover:text-slate-200 px-2.5 py-1 rounded-lg hover:bg-slate-800 border border-slate-800 transition-all"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>Reset</span>
          </button>
        )}
      </div>

      {/* Messages Stream */}
      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center p-8 text-slate-500 space-y-3">
            <div className="w-12 h-12 rounded-2xl bg-slate-800/60 border border-slate-700/60 flex items-center justify-center text-slate-400">
              <Sparkles className="w-6 h-6 text-indigo-400" />
            </div>
            <div className="max-w-md">
              <h3 className="text-sm font-semibold text-slate-300">Ready for Evidence-Grounded Research</h3>
              <p className="text-xs text-slate-500 mt-1">
                Upload PDFs and ask questions. Every response is strictly grounded in retrieved evidence with verified page citations and bounded agent retries.
              </p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {[
                  "Summarize the key findings",
                  "What evidence supports the main conclusion?",
                  "What limitations are mentioned?",
                ].map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => setQuery(suggestion)}
                    className="rounded-full border border-slate-700 bg-slate-900/70 px-3 py-1.5 text-xs text-slate-300 transition-colors hover:border-indigo-500/60 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {messages.map((m) => (
          <div
            key={m.id}
            className={`flex items-start space-x-3 ${
              m.role === "user" ? "flex-row-reverse space-x-reverse" : ""
            }`}
          >
            <div
              className={`w-7 h-7 rounded-lg flex items-center justify-center shrink-0 text-xs font-bold ${
                m.role === "user"
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-800 border border-slate-700 text-indigo-400"
              }`}
            >
              {m.role === "user" ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
            </div>

            <div
              className={`max-w-[82%] rounded-2xl p-4 text-sm leading-relaxed shadow-sm ${
                m.role === "user"
                  ? "bg-indigo-600 text-white rounded-tr-none"
                  : "bg-slate-900 border border-slate-800 text-slate-200 rounded-tl-none"
              }`}
            >
              {m.has_knowledge_gap && (
                <div className="mb-2.5 px-3 py-1.5 rounded-lg bg-amber-950/40 border border-amber-800/60 text-amber-300 text-xs flex items-center gap-1.5">
                  <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                  <span>Knowledge Gap Detected — Insufficient document evidence</span>
                </div>
              )}

              <div className="whitespace-pre-wrap">{m.content}</div>

              {m.claims && m.claims.length > 0 ? (
                <section className="mt-4 border-t border-slate-800 pt-3" aria-label="Claim-level evidence map">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <h3 className="text-xs font-semibold text-slate-300">Claim-level evidence map</h3>
                    <span className="rounded-full border border-amber-800/70 bg-amber-950/40 px-2 py-0.5 text-[10px] text-amber-300">
                      Review links
                    </span>
                  </div>
                  <p className="mb-3 text-[11px] leading-relaxed text-slate-500">
                    Source links are proposed by the language model and matched to retrieved passages; they are not an independent truth verification.
                  </p>
                  <div className="space-y-3">
                    {m.claims.map((claim, index) => {
                      const linkedCitations = (m.citations || []).filter((citation) => claim.source_ids.includes(citation.source_id));
                      return (
                        <div key={`${index}-${claim.text}`} className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                          <p className="text-xs leading-relaxed text-slate-200">{claim.text}</p>
                          {linkedCitations.length > 0 ? (
                            <>
                              <CitationCard citations={linkedCitations} />
                              <div className="mt-3 rounded-lg border border-slate-800 bg-slate-900/60 p-2.5">
                                <p className="mb-2 text-[10px] text-slate-400">Help train NEXUS: how does each passage relate to this claim?</p>
                                {linkedCitations.map((citation) => {
                                  const annotationKey = `${citation.source_id}:${claim.text}`;
                                  return (
                                    <div key={annotationKey} className="mb-2 last:mb-0">
                                      <p className="mb-1 truncate text-[10px] text-slate-500">{citation.document_name} · p.{citation.page_number}</p>
                                      <div className="flex flex-wrap items-center gap-1.5">
                                        {(["supports", "contradicts", "insufficient"] as const).map((label) => (
                                          <button
                                            key={label}
                                            type="button"
                                            onClick={() => handleEvidenceLabel(claim.text, citation.source_id, label)}
                                            disabled={annotationStatus[annotationKey] === "Saving…"}
                                            className="rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:border-indigo-500 hover:text-white disabled:opacity-50"
                                          >
                                            {label}
                                          </button>
                                        ))}
                                        {annotationStatus[annotationKey] && <span className="text-[10px] text-emerald-300">{annotationStatus[annotationKey]}</span>}
                                      </div>
                                    </div>
                                  );
                                })}
                                {annotationError && <p role="alert" className="mt-2 text-[10px] text-rose-300">{annotationError}</p>}
                              </div>
                            </>
                          ) : (
                            <p className="mt-2 text-[11px] text-amber-300">No retrieved passage was linked to this claim. Review it before relying on it.</p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </section>
              ) : m.citations && m.citations.length > 0 ? (
                <CitationCard citations={m.citations} />
              ) : null}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex items-start space-x-3">
            <div className="w-7 h-7 rounded-lg bg-slate-800 border border-slate-700 text-indigo-400 flex items-center justify-center shrink-0">
              <Bot className="w-4 h-4" />
            </div>
            <div className="max-w-[82%] w-full">
              <AgentStatus activityLogs={currentLogs} isLoading={true} />
            </div>
          </div>
        )}

        <div ref={scrollRef} />
      </div>

      {/* Input Form */}
      <form onSubmit={handleSend} className="border-t border-slate-800 bg-slate-900/60 p-3 sm:p-4">
        <div className="relative flex items-end">
          <label htmlFor="research-question" className="sr-only">Ask a question about your research documents</label>
          <textarea
            id="research-question"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void handleSend();
              }
            }}
            placeholder="Ask a question about your uploaded research documents..."
            rows={2}
            disabled={isLoading}
            className="max-h-40 min-h-[76px] w-full resize-y rounded-xl border border-slate-800 bg-slate-950 px-4 py-3 pr-14 text-sm text-slate-100 placeholder-slate-500 transition-colors focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 disabled:opacity-50"
          />
          <button
            type="submit"
            aria-label="Send question"
            disabled={isLoading || !query.trim()}
            className="absolute bottom-2 right-2 rounded-lg bg-indigo-600 p-2.5 text-white transition-all hover:bg-indigo-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 disabled:pointer-events-none disabled:opacity-30"
          >
            {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </div>
        <p className="mt-2 text-[10px] text-slate-500">Enter to send · Shift + Enter for a new line</p>
      </form>
    </div>
  );
}
