"use client";

import React, { useState, useRef } from "react";
import { UploadCloud, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";
import { api, DocumentItem } from "../lib/api";

interface UploaderProps {
  onUploadSuccess: (doc: DocumentItem) => void;
}

export function Uploader({ onUploadSuccess }: UploaderProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [lastUploaded, setLastUploaded] = useState<string | null>(null);
  const [lastUploadStatus, setLastUploadStatus] = useState<DocumentItem["status"] | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File): Promise<boolean> => {
    const extension = file.name.toLowerCase().split(".").pop();
    const isPdf = extension === "pdf" && (!file.type || file.type === "application/pdf");
    const isImage = ["jpg", "jpeg", "png", "webp"].includes(extension || "") && (!file.type || ["image/jpeg", "image/png", "image/webp"].includes(file.type));
    const isVideo = ["mp4", "mov", "webm"].includes(extension || "") && (!file.type || ["video/mp4", "video/quicktime", "video/webm"].includes(file.type));
    if (!isPdf && !isImage && !isVideo) {
      setUploadError("Supported types are PDF, JPEG, PNG, WebP, MP4, MOV, and WebM.");
      return false;
    }
    const maxSize = isVideo ? 100 * 1024 * 1024 : isImage ? 15 * 1024 * 1024 : 25 * 1024 * 1024;
    if (file.size > maxSize) {
      setUploadError(`File size exceeds ${Math.round(maxSize / (1024 * 1024))} MB limit.`);
      return false;
    }

    setUploadError(null);
    setIsUploading(true);

    try {
      const doc = await api.uploadDocument(file);
      setLastUploaded(doc.filename);
      setLastUploadStatus(doc.status);
      onUploadSuccess(doc);
      return true;
    } catch (error: unknown) {
      setUploadError(error instanceof Error ? error.message : "Upload and ingestion failed.");
      return false;
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const handleFiles = async (files: File[]) => {
    setUploadError(null);
    for (const file of files) {
      const uploaded = await handleFile(file);
      if (!uploaded) break;
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files?.length) {
      void handleFiles(Array.from(e.dataTransfer.files));
    }
  };

  return (
    <div className="w-full">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => !isUploading && fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if ((event.key === "Enter" || event.key === " ") && !isUploading) {
            event.preventDefault();
            fileInputRef.current?.click();
          }
        }}
        className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
          isDragging
            ? "border-indigo-500 bg-indigo-950/30"
            : "border-slate-700 hover:border-slate-500 bg-slate-900/50 hover:bg-slate-900/80"
        } ${isUploading ? "opacity-60 pointer-events-none" : ""}`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept="application/pdf,image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm"
          className="hidden"
          multiple
          onChange={(e) => {
            if (e.target.files?.length) {
              void handleFiles(Array.from(e.target.files));
            }
          }}
        />

        <div className="flex flex-col items-center justify-center space-y-3">
          <div className="w-12 h-12 rounded-full bg-indigo-500/10 flex items-center justify-center text-indigo-400">
            {isUploading ? (
              <Loader2 className="w-6 h-6 animate-spin" />
            ) : (
              <UploadCloud className="w-6 h-6" />
            )}
          </div>
          <div>
            <p className="text-sm font-medium text-slate-200">
              {isUploading
                ? "Analyzing and indexing your media..."
                : "Click or drag PDFs, images, or videos to upload"}
            </p>
              <p className="text-xs text-slate-500 mt-1">
              PDF (25 MB), image (15 MB), video up to 120 seconds (100 MB). Video evidence uses sampled frames; brief events may be missed.
            </p>
          </div>
        </div>
      </div>

      {uploadError && (
        <div className="mt-3 p-3 rounded-lg bg-rose-950/50 border border-rose-800 text-rose-300 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0 text-rose-400" />
          <span>{uploadError}</span>
        </div>
      )}

      {lastUploaded && !uploadError && (
        <div className="mt-3 p-3 rounded-lg bg-emerald-950/40 border border-emerald-800 text-emerald-300 text-xs flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-400" />
          <span>
            {lastUploadStatus === "ready" ? "Successfully indexed: " : "Queued for ingestion: "}
            <strong>{lastUploaded}</strong>
          </span>
        </div>
      )}
    </div>
  );
}
