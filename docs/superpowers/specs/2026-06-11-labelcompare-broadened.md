# LabelCompare — Broadened TTB COLA Compliance Analysis (Design Update)

**Date**: 2026-06-11  
**Status**: Draft / In implementation  
**Supersedes / extends**: `2026-06-11-labelcompare-design.md` (original narrow prototype focused on form-vs-label matching + one hardcoded health warning check for three sample PDFs).

## Purpose
Broaden LabelCompare to accept **any** OMB No. 1513-0020 (TTB F 5100.31 "Application for and Certification/Exemption of Label/Bottle Approval") document submission and use the local llama.cpp LLM capabilities (primarily the text model) to **analyze the full OCR-captured text** and verify that the submitted labels meet applicable TTB labeling requirements.

The tool remains a **local triage / analysis aid** for compliance agents or producers. It must:
- Always expose raw OCR transcripts and evidence quotes.
- Never claim to replace official TTB review or provide legal approval.
- Support the variety of real submissions: different commodities (wine, distilled spirits, malt beverages), domestic vs. imported, single vs. multi-page, form + attached label artwork (possibly multiple labels), dirty scans, etc.

## Key Shifts from Original Prototype
- **From**: Rigid 7-field extraction + pure-Python pass/fail on brand/ABV + exact 27 CFR 16.21 ALL-CAPS warning. Tuned to three specific sample PDFs and the "application form data vs. label text after AFFIX COMPLETE SET..." pattern.
- **To**: Generalized document handling + rich OCR + LLM-driven compliance analysis grounded in a static knowledge base of core requirements + continued hybrid deterministic checks for bright-line rules (especially the health warning).

The original "application vs. printed label" comparison remains useful (catches inconsistencies between what was declared on the form and what is actually printed) and is kept as one view. A new "Regulatory Compliance Analysis" view is added, powered by LLM reasoning over the full transcript.

## Architecture (Updated)
```
browser ──> FastAPI :1776
              ├── applications/          (any OMB 1513-0020 PDFs + label art)
              ├── results.json           (extended schema, backwards-compatible)
              ├──> GLM-OCR :8090         (page PNG(s) -> verbatim transcripts; support full pages + optional views)
              └──> Qwen (text) :8080     (transcript -> structured extraction + compliance findings)

Pipeline per submission:
1. Sanitize + render pages (PyMuPDF; keep tolerant dirty-PDF handling; make multi-view configurable or secondary).
2. OCR: produce high-fidelity full-page (and/or tiled) transcripts, preserving case/punctuation. Concatenate with page markers.
3. Extraction (Qwen, grammar-constrained or structured): 
   - Detect commodity / product category.
   - Extract key form declarations (brand, class/type, ABV, net contents, responsible party, origin, etc.).
   - Extract prominent label text blocks as they appear on the artwork.
4. Compliance Analysis (Qwen, grounded):
   - Load relevant sections from `knowledge/ttb_label_requirements.md`.
   - Analyze label text against requirements for the declared category.
   - Cross-check key items against form declarations.
   - Produce structured findings (requirement, status, verbatim evidence, citation, notes).
5. Deterministic post-processing (Python):
   - Strict health warning validation (enhanced from original verify.py).
   - Simple numeric/brand consistency helpers.
   - Overall roll-up (e.g., any "fail" on required items → overall needs_review or fail).
6. Store rich result; serve to UI.

The LLMs are used for extraction and *analysis/reasoning with evidence*. Bright-line statutory requirements (health warning text + caps) remain code-enforced where feasible for auditability and precision.
```

## Components (Changes)
- `server/pdf.py`: Minor generalization; keep `render_page_views` and add or expose simpler full-page rendering. Add page classification hints if useful.
- `server/llm.py`: 
  - Generalized `EXTRACT_PROMPT` (remove hard assumption of "AFFIX COMPLETE SET OF LABELS"; handle varied form + artwork layouts).
  - New `classify_product_category(transcript)` or integrated in one call.
  - New `analyze_compliance(transcript, extracted_form, commodity)` that loads the knowledge file and returns structured findings.
  - Keep `ocr_page`, `_post`, error handling, timeouts. Support larger max_tokens for analysis if the model allows.
- `server/verify.py`: Keep and enhance `check_warning`, `parse_abv`, `brands_match`, `normalize`, `verdict` (for the "form vs label fields" comparison view). Add helpers for other bright-line checks if they emerge as reliable in code.
- `server/store.py`: Minor — support richer result payloads; old results should still load.
- `server/app.py`: 
  - In `/analyze`: run the full new pipeline (OCR → extract → compliance analysis → deterministic checks).
  - Return extended entry: keep `result` (for old field table) + new `compliance` object + `transcripts` (raw OCR for transparency).
  - Update progress stages (rendering, OCR, extracting, analyzing compliance, verifying).
- `knowledge/ttb_label_requirements.md`: New static grounding file (concise excerpts + instructions for the LLM on how to use it). Checked into the repo; user can extend.
- `web/`: 
  - Add "Compliance Analysis" / "Regulatory Findings" section (table or cards: Requirement | Status | Evidence (verbatim) | Citation | Notes).
  - Keep existing "Application vs. Label" field table (or integrate).
  - Prominently display or link to the raw full OCR transcript(s).
  - Update verdict language from "PASSES minimum requirements" to something like "Analysis complete — see findings" (emphasize it is an aid).
  - Style updates for new sections.
- Tests: Extend with mocked LLM responses for the new analysis step. Keep coverage of PDF sanitizing and warning logic. Add tests that exercise the knowledge loading and prompt construction.
- Docs: Update README (new capabilities, limitations, knowledge file). Add or replace the design spec with this broadened version. Keep the original plan for history.

## LLM Usage & Grounding Strategy (Critical for 7B-class model)
- OCR prompt stays generic and high-fidelity ("Transcribe all text exactly as printed...").
- Extraction uses JSON schema for structure.
- Compliance analysis prompt:
  - System-like instructions: "You are a careful TTB label compliance analyst. Use only the provided transcript and the requirements in the KNOWLEDGE section. Quote verbatim evidence. Be conservative on unclear OCR."
  - Include the full or relevant slice of `knowledge/ttb_label_requirements.md`.
  - Ask for structured output (JSON schema) with `findings` array + `overall_assessment` + `product_category`.
  - Few-shot examples (in prompt or separate) of good vs. bad findings for the 7B model.
- Temperature low (0). Max tokens sufficient for detailed findings.
- If the 7B struggles with long transcripts + knowledge, strategies: 
  - Chunk by page or by section (form first, then label blocks).
  - First call for classification + key extractions, second call for analysis on focused excerpts.
  - Always return the raw transcript so humans can read the source.

**Health warning**: The LLM will be instructed to locate candidate text. The Python `check_warning` (or improved version) will be run on the best candidate and its result will be authoritative for that item and included in findings.

## Result Shape (High Level, Backwards Compatible)
```json
{
  "status": "pass" | "fail" | "needs_review" | "error",
  "result": { /* legacy field-by-field comparison for form vs label (brand, alcohol, warning, etc.) */ },
  "compliance": {
    "product_category": "wine" | "distilled_spirits" | "malt_beverage" | "unknown",
    "overall_assessment": "...",
    "findings": [
      {
        "requirement": "Health warning statement",
        "citation": "27 CFR Part 16",
        "status": "pass" | "fail" | "missing" | "needs_review",
        "evidence": "verbatim quote from OCR...",
        "notes": "..."
      },
      ...
    ],
    "raw_transcript_summary": "..."
  },
  "extraction": { /* richer than before */ },
  "transcripts": ["page 1 full OCR...", ...],
  "error": null
}
```

Old results without `compliance` should render gracefully (show what was there + note that re-analysis is recommended for full features).

## Scope and Limitations (Updated)
**In scope for this broadening**:
- Any scanned or image-based OMB 1513-0020 submission (form + label artwork).
- Core mandatory information + health warning across the three main commodities.
- Hybrid LLM + code analysis with full evidence trail.
- Local-only operation using the existing llama.cpp endpoints.

**Out of scope (same as original or newly noted)**:
- Formula approval, COLA Online electronic filing integration, actual submission to TTB.
- Full legal opinion or guarantee of approval.
- Non-alcohol or <0.5% ABV products.
- Detailed type-size / placement / graphic design compliance beyond what OCR + text analysis can reliably surface (the tool can flag "appears small or low-contrast per OCR" but cannot measure pixels perfectly).
- Parallel processing (still sequential for model resource reasons).
- Authentication / multi-user (binds 0.0.0.0 for LAN use on trusted network).

**Model limitations** (must be surfaced in UI and docs):
- OCR quality depends on the GLM-OCR model and scan quality. Poor scans → mark items "needs_review".
- The 7B text model can miss nuances or over-generalize; all findings must be treated as suggestions with human review of the raw transcript.
- Long documents may require chunking; performance is still minutes per submission.

## Testing & Validation
- Unit tests for new functions with mocked LLM.
- Re-run on the three existing samples; they should still produce useful (if now richer) output. The health warning should still be strictly validated.
- Manual testing with additional real (anonymized) OMB 1513-0020 submissions covering different commodities.
- UI must always allow viewing the full raw OCR so a compliance agent can confirm the LLM didn't hallucinate evidence.

## Migration / Backwards
- Existing `results.json` entries continue to work for display.
- Re-analyzing old PDFs will produce the new richer format.
- Update the knowledge file when regulations change; the prompt construction should re-read it on each analysis (or cache with mtime).

## Next Steps (Implementation Order)
1. Knowledge file + prompt engineering in llm.py.
2. Generalized extraction + new compliance analysis function.
3. Backend pipeline and result storage updates.
4. Frontend enhancements for findings display + raw transcript viewer.
5. Tests, docs (this spec + README), sample re-validation.
6. Iterate on prompt quality and knowledge file based on real documents.

This design preserves the strengths of the original (deterministic core for the strict warning, full transparency, local-only, simple stack) while addressing the request to handle arbitrary OMB 1513-0020 documents and leverage the LLM for deeper analysis of the captured text against the actual requirements.
