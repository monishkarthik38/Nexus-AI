"use client";

import React from "react";
import { FileText, Trash2, CheckCircle2, Clock, AlertTriangle, Image as ImageIcon, Video as VideoIcon } from "lucide-react";
import { DocumentItem } from "../lib/api";

interface DocumentListProps {
  documents: DocumentItem[];
  selectedDocIds: string[];
  onToggleSelect: (id: string) => void;
  onDeleteDoc: (id: string) => void;
}

export function DocumentList({
  documents,
  selectedDocIds,
  onToggleSelect,
  onDeleteDoc,
}: DocumentListProps) {
  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  if (documents.length === 0) {
    return (
      <div className="py-8 text-center text-slate-500 text-sm">
        No documents uploaded yet. Upload a PDF above to begin research.
      </div>
    );
  }

  return (
    <div className="space-y-2 max-h-[380px] overflow-y-auto pr-1">
      {documents.map((doc) => {
        const isSelected = selectedDocIds.includes(doc.id);
        return (
          <div
            key={doc.id}
            onClick={() => onToggleSelect(doc.id)}
            className={`p-3 rounded-xl border transition-all cursor-pointer flex items-center justify-between group ${
              isSelected
                ? "border-indigo-500 bg-indigo-950/20"
                : "border-slate-800 bg-slate-900/60 hover:border-slate-700"
            }`}
          >
            <div className="flex items-center space-x-3 overflow-hidden">
              <input
                type="checkbox"
                checked={isSelected}
                onChange={() => onToggleSelect(doc.id)}
                className="rounded border-slate-700 bg-slate-800 text-indigo-600 focus:ring-0 cursor-pointer"
                onClick={(e) => e.stopPropagation()}
              />
              {doc.media_type === "image" ? (
                <ImageIcon className="w-5 h-5 text-violet-400 shrink-0" />
              ) : doc.media_type === "video" ? (
                <VideoIcon className="w-5 h-5 text-amber-400 shrink-0" />
              ) : (
                <FileText className="w-5 h-5 text-indigo-400 shrink-0" />
              )}
              <div className="truncate">
                <p className="text-sm font-medium text-slate-200 truncate" title={doc.filename}>
                  {doc.filename}
                </p>
                <div className="flex items-center space-x-2 text-xs text-slate-500 mt-0.5">
                  <span>{doc.media_type === "video" ? `${doc.page_count} sampled frames` : doc.media_type === "image" ? "image evidence" : `${doc.page_count} pages`}</span>
                  {doc.duration_seconds ? <><span>•</span><span>{doc.duration_seconds}s</span></> : null}
                  <span>•</span>
                  <span>{formatSize(doc.file_size)}</span>
                  <span>•</span>
                  {doc.status === "ready" && (
                    <span className="flex items-center text-emerald-400">
                      <CheckCircle2 className="w-3 h-3 mr-1" /> Ready
                    </span>
                  )}
                  {doc.status === "processing" && (
                    <span className="flex items-center text-amber-400">
                      <Clock className="w-3 h-3 mr-1 animate-spin" /> Queued / processing
                    </span>
                  )}
                  {doc.status === "failed" && (
                    <span className="flex items-center text-rose-400" title={doc.error_message}>
                      <AlertTriangle className="w-3 h-3 mr-1" /> Failed
                    </span>
                  )}
                </div>
              </div>
            </div>

            <button
              onClick={(e) => {
                e.stopPropagation();
                onDeleteDoc(doc.id);
              }}
              title="Delete document"
              className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-950/40 transition-all"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
