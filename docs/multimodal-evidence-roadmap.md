# NEXUS multimodal evidence roadmap

## Product goal

Extend NEXUS from PDF evidence research to an **auditable multimodal evidence workspace**. A user should be able to ask a question about PDFs, images, and video and inspect exactly which page, image region, video frame, or transcript segment supports or contradicts each answer claim.

The interface must describe evidence links and model judgments as *AI-assisted*, not as proof or independent verification. Human review remains available for every modality.

## Current baseline and gaps

- The upload endpoint accepts PDFs only, validates the PDF header, and synchronously extracts page text before indexing.
- Qdrant points and SQL chunks are text-based; citations identify a chunk, document, page, and excerpt.
- Evidence annotations currently snapshot a text chunk and label a claim/passage pair.
- The small NEXUS evidence verifier is a text-only TF-IDF baseline, not a vision model. It must not be presented as capable of checking image or video evidence.
- Upload identity is currently supplied as an `owner_id` field by the client. Before exposing private media beyond a local single-user demo, replace this with authenticated server-side identity and enforce authorization on upload, retrieval, viewing, annotations, and deletion.

## Implementation status (MVP)

The initial local MVP now accepts JPEG, PNG, and WebP images plus MP4, MOV, and WebM videos. Images are described at upload time when Gemini vision is configured; videos are limited to 120 seconds and five frames are sampled for descriptions. Citations carry image/video-frame locators and the UI can show the image or seek the video player to a cited timestamp. If Gemini is not configured, files can still be stored but their visual contents are explicitly not analyzed. This synchronous, local implementation is for development only; it is not production-hardened and does not provide OCR for image text, asynchronous jobs, audio transcripts, or a fully authenticated private media service.

## Target experience

1. Upload an image or video alongside PDFs.
2. Ask a question such as "Does this image show the label described in the report?" or "At what point does the clip show the safety indicator turning red?"
3. Receive concise claims, each linked to inspectable evidence:
   - PDF: document + page + passage.
   - Image: document + image + optional normalized bounding box/region + OCR text when available.
   - Video: document + timestamp + sampled frame, plus transcript timestamp when audio is enabled.
4. Mark each claim/evidence item as `supports`, `contradicts`, or `insufficient`; optionally flag illegible, ambiguous, or wrong-time evidence.
5. Review and export human-labeled examples with whole source documents held out from training.

## Recommended phased implementation

### Phase 0 — Decide the media contract and safety boundaries

- Define allowed image/video formats, per-file size, image pixel limit, video duration, total upload quota, and retention rules.
- Store MIME type, media type, content hash, size, processing state, and parser/model versions for every upload.
- Verify content by signature as well as extension and declared MIME; never trust browser-supplied MIME alone.
- Keep original files private. Serve previews through owner-authorized endpoints or short-lived signed URLs, never public static paths.
- Treat uploaded OCR, subtitles, and visible text as untrusted input; preserve existing prompt-injection defenses and add media-specific adversarial tests.
- Obtain permission to analyze and retain uploaded media, especially identifiable people, private locations, health data, and copyrighted material.

**Exit criteria:** documented limits, format allowlist, authorization design, retention policy, and an explicit local-development versus production storage configuration.

### Phase 1 — Images first (recommended next implementation)

- Extend upload validation to selected raster image types (initially JPEG, PNG, and WebP; avoid SVG because it can contain active content).
- Add a parser abstraction with typed output rather than extending `PDFParser` into a catch-all. Image output should include OCR text where useful, image dimensions, and an image-level evidence item even when OCR finds no text.
- Preserve the original image and create safe, size-limited previews. Strip or avoid exposing EXIF metadata unless a supported use case requires it.
- Add an image-capable model adapter behind a provider interface. Request structured observations with confidence and region coordinates when supported. Do not assert details not visible in the image.
- Add typed citation locators so the UI can open the original image and optionally highlight an approximate region.
- Add image-specific human labels and tests for OCR, no-text images, unsupported MIME, malformed files, oversized dimensions, authorization, and citation locator integrity.

**Exit criteria:** an uploaded image can be selected, asked about, cited in an answer, opened from its citation, and labeled. Existing PDF flow and tests continue to pass.

### Phase 2 — Video as timestamped visual evidence

- Accept a small initial set of video containers/codecs (for example MP4/H.264), with strict byte and duration limits. Inspect actual streams via a trusted media tool such as FFmpeg; reject malformed or unsupported streams.
- Do not embed or send every frame. Run ingestion asynchronously: probe metadata, sample frames at a conservative interval and/or scene changes, resize frames, and retain timestamps linking each sample to the source video.
- Index frame observations as evidence items with stable frame IDs and timestamps. Keep original video private and generate authorized preview/seek links.
- Start with silent/video-frame analysis; add audio transcription only as a separately configurable follow-up with timestamps and an explicit privacy notice. Keep transcript evidence distinct from visual frame evidence.
- Make query-time retrieval identify relevant frame windows, then ask the vision model to analyze only those windows. Answers should cite time ranges and sampled frames, and disclose that sampling can miss brief events.
- Queue work with retry, cancellation, status/progress, and cleanup; never perform expensive video decoding in the request thread.

**Exit criteria:** a user can locate a cited time range and inspect its frame; tests cover duration, size, timeout, parser failure, frame timestamps, owner boundaries, and deletion cleanup.

### Phase 3 — Cross-modal evidence and contradiction review

- Retrieve jointly from PDF passages, OCR text, image observations, frame observations, and (if enabled) transcript segments.
- Show corroboration and disagreement across modalities, e.g. report claim vs. photo label vs. video event, with each source kept distinct.
- Make the answer schema include `evidence_refs` with modality-specific locator data, rather than overloading `page_number` and `excerpt`.
- Use explicit statuses such as `model_suggests_support`, `model_suggests_contradiction`, `human_confirmed`, and `unreviewed`; keep classifier confidence separate from human label.

**Exit criteria:** a claim can cite multiple modalities, contradictions are visible, and each link can be opened at the correct page/region/time.

### Phase 4 — Train NEXUS multimodal models responsibly

- Keep the existing text verifier text-only. Add a modality-aware dataset schema that references a text claim plus an authorized image/frame asset and a human label.
- Collect diverse, permissioned, representative human labels. Split train/test by entire source document or video—not by near-duplicate frames—to prevent leakage.
- Establish baselines first: existing vision-language model with structured prompts, OCR-only for text-heavy images, and text verifier on transcripts. Measure per-class precision/recall, calibration, failure slices, and abstention.
- Fine-tune an open-weight vision-language model or a compact vision-language classifier only after the dataset and compute requirements are understood. Version training data, code, weights, and evaluation reports; keep holdout data private and untouched.
- Do not use generated/synthetic labels as ground truth without human review. Do not market model predictions as verified facts.

**Exit criteria:** meaningful independent test results, documented limitations, privacy review, and a rollback path before any trained model affects user-facing answers.

## Architecture changes to plan for

- **Ingestion:** replace the PDF-only route internals with a media-type dispatcher, separate parsers, asynchronous job status for expensive formats, and idempotent processing.
- **Persistence:** add typed evidence records/locators and parser version metadata. Maintain relationships from an evidence item to its parent document and original stored asset.
- **Retrieval:** keep modality-aware metadata and filters; text search remains useful for OCR/transcripts, while image/frame retrieval may need vision embeddings and a multimodal reranker.
- **API:** typed upload responses, processing status, authorized preview/stream endpoints, and evidence references in chat responses.
- **Frontend:** generalized uploader with format-specific limits/progress; image preview; video player with timestamp seeking; claim-level review controls and modality labels.
- **Evaluation:** image/video-specific benchmark sets with human ground truth, document-disjoint holdouts, and separate metrics per modality. Never infer benchmark success from citation IDs alone.
- **Operations:** private object storage, background worker/queue, resource limits, observability, retention/deletion, and safe temporary-file cleanup.

## Priority recommendation

Implement in this order: **authorization and media contract → image upload + image citations → human image labels → document-disjoint multimodal evaluation → sampled video frames → optional timestamped audio transcription → multimodal model training**. Images are a much smaller, testable step than video; video adds significant storage, compute, latency, and sampling risk.

Do not immediately train a video model. First make image/video sources inspectable and collect trustworthy human labels. NEXUS's differentiator is the traceable evidence workflow, not a premature claim of training a large foundation model.
