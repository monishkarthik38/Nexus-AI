"use client";

import React, { useEffect, useState } from "react";
import Image from "next/image";
import { BookOpen, FileText, ChevronRight, X } from "lucide-react";
import { Citation, getDocumentPreviewUrl, getVideoFramePreviewUrl } from "../lib/api";

interface CitationCardProps {
  citations: Citation[];
}

export function CitationCard({ citations }: CitationCardProps) {
  const [activeModalCitation, setActiveModalCitation] = useState<Citation | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    let objectUrl: string | null = null;
    setPreviewUrl(null);
    setPreviewError(null);
    if (!activeModalCitation?.document_id) return;

    const loadPreview = activeModalCitation.locator_type === "video_frame"
      ? getVideoFramePreviewUrl(activeModalCitation.document_id, activeModalCitation.locator_value || "0")
      : activeModalCitation.locator_type === "image"
        ? getDocumentPreviewUrl(activeModalCitation.document_id)
        : null;
    if (!loadPreview) return;

    void loadPreview.then((url) => {
      objectUrl = url;
      if (disposed) URL.revokeObjectURL(url);
      else setPreviewUrl(url);
    }).catch((error: unknown) => {
      if (!disposed) setPreviewError(error instanceof Error ? error.message : "Could not load preview.");
    });
    return () => {
      disposed = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [activeModalCitation]);

  if (!citations || citations.length === 0) return null;

  return (
    <div className="mt-3 pt-3 border-t border-slate-800">
      <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-400 mb-2">
        <BookOpen className="w-3.5 h-3.5 text-indigo-400" />
        <span>Grounded Citations ({citations.length}):</span>
      </div>

      <div className="flex flex-wrap gap-2">
        {citations.map((c, i) => (
          <button
            key={i}
            onClick={() => setActiveModalCitation(c)}
            className="inline-flex items-center space-x-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-slate-800 hover:bg-slate-700/80 border border-slate-700 text-indigo-300 transition-all hover:scale-[1.02]"
          >
            <FileText className="w-3 h-3 text-indigo-400" />
            <span className="truncate max-w-[150px]">{c.document_name}</span>
            <span className="bg-indigo-950 text-indigo-300 px-1.5 py-0.2 rounded text-[10px] font-mono border border-indigo-800">
              {c.locator_type === "video_frame" ? `${c.locator_value}s` : c.locator_type === "image" ? "IMAGE" : `P.${c.page_number}`}
            </span>
            <ChevronRight className="w-3 h-3 text-slate-500" />
          </button>
        ))}
      </div>

      {/* Citation Preview Modal */}
      {activeModalCitation && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 shadow-2xl relative animate-in fade-in zoom-in-95 duration-150">
            <button
              onClick={() => setActiveModalCitation(null)}
              className="absolute top-4 right-4 text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800"
            >
              <X className="w-5 h-5" />
            </button>

            <div className="flex items-center space-x-2 text-indigo-400 text-xs font-semibold uppercase tracking-wider mb-2">
              <FileText className="w-4 h-4" />
              <span>Source Evidence Preview</span>
            </div>

            <h3 className="text-base font-semibold text-slate-100 mb-1">
              {activeModalCitation.document_name}
            </h3>
            <p className="text-xs text-slate-400 mb-4 font-mono">
              {activeModalCitation.locator_type === "video_frame"
                ? `Video timestamp ${activeModalCitation.locator_value}s`
                : activeModalCitation.locator_type === "image"
                  ? "Image evidence"
                  : `Page ${activeModalCitation.page_number}`} • Source ID: {activeModalCitation.source_id}
            </p>

            {activeModalCitation.document_id && activeModalCitation.locator_type === "image" && previewUrl && (
              <Image
                src={previewUrl}
                alt={`Evidence from ${activeModalCitation.document_name}`}
                width={1200}
                height={900}
                unoptimized
                className="mb-4 max-h-[55vh] w-full rounded-xl border border-slate-800 bg-black object-contain"
              />
            )}

            {activeModalCitation.document_id && activeModalCitation.locator_type === "video_frame" && previewUrl && (
              <Image
                src={previewUrl}
                alt={`Video frame at ${activeModalCitation.locator_value} seconds from ${activeModalCitation.document_name}`}
                width={1200}
                height={900}
                unoptimized
                className="mb-4 max-h-[55vh] w-full rounded-xl border border-slate-800 bg-black object-contain"
              />
            )}
            {previewError && <p role="alert" className="mb-4 text-xs text-rose-300">{previewError}</p>}

            <div className="bg-slate-950 border border-slate-800/80 rounded-xl p-4 text-slate-300 text-sm italic leading-relaxed">
              &ldquo;{activeModalCitation.excerpt}&rdquo;
            </div>

            <div className="mt-5 flex justify-end">
              <button
                onClick={() => setActiveModalCitation(null)}
                className="px-4 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 transition-all"
              >
                Close Preview
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
