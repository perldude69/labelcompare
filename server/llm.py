"""Clients for the local llama.cpp servers."""
import base64
import json
import os
import pathlib
import re

import httpx


KNOWLEDGE_PATH = (
    pathlib.Path(__file__).resolve().parent.parent / "knowledge" / "ttb_label_requirements.md"
)


def load_knowledge() -> str:
    """Load the static TTB requirements knowledge for grounding compliance analysis."""
    try:
        return KNOWLEDGE_PATH.read_text(encoding="utf-8")
    except Exception as e:
        return f"[Knowledge base unavailable: {e}. Falling back to built-in core rules only.]"


OCR_URL = os.environ.get("OCR_URL", "http://127.0.0.1:8090/v1/chat/completions")
QWEN_URL = os.environ.get("QWEN_URL", "http://127.0.0.1:8080/v1/chat/completions")
OCR_TIMEOUT = 240
QWEN_TIMEOUT = 180

OCR_PROMPT = (
    "Transcribe all text in this image exactly as printed. Preserve "
    "capitalization and punctuation. Output only the transcribed text."
)

EXTRACT_PROMPT = """\
The text below is a concatenated OCR transcript from multiple rendered views \
(full page + overlapping upper/lower region crops) of a scanned TTB alcohol label \
application / COLA submission (OMB No. 1513-0020 form + submitted label artwork).

The transcript is structured with markers:
=== PAGE N VIEW M ===
...text from that specific image crop...

There are usually two distinct sources of text mixed together in the images:
1. APPLICATION / FORM PORTION: Typed or printed form fields, numbered items \
   (e.g. "9. FORMULA 45% ACV", "13. EMAIL ADDRESS ...", "Brand Name:", \
   "Alcohol Content:", "Net Contents:", "Bottler:", official TTB headers, \
   "AUTHORIZED SIGNATURE, ALCOHOL AND TOBACCO TAX AND TRADE BUREAU"). These \
   are the applicant's declarations on the government form. Text here is \
   usually in a standard form layout, often smaller or in boxes/fields.
2. LABEL ARTWORK PORTION: The actual product label design text as it will \
   appear on the bottle (prominent brand logo text like "Smirnoff", the full \
   government warning block in its designed layout, net contents like "375 mL" \
   in the label's style, "PRODUCED BY ..." or "BOTTLED BY ..." in the label's \
   typography, website, any other decorative or mandatory label copy). This \
   text is part of the visual label graphic.

Your task is to extract two objects with strict separation of sources.

"application": ONLY values that come from the form / application portion \
  (the numbered fields, declarations the applicant filled or the form pre-printed \
  for this submission). Use the exact wording that appears in the form context.

  Special note for brand_name: The form almost always has an explicit brand declaration \
  (e.g. a field labeled "Brand Name", "Brand", or in a numbered item). The label artwork \
  will usually show the same brand name prominently as graphic text. Extract the form \
  version for "application" (even if the exact same string also appears in the label design). \
  Example: if the form says "Smirnoff" and the label artwork also says "Smirnoff", put \
  "Smirnoff" in both "application"."brand_name" and "label"."brand_name".

"label": ONLY values that are actually printed as part of the label artwork \
  design. Preserve exact capitalization, line breaks, and punctuation from \
  the transcript. For "government_warning", copy the full warning verbatim \
  starting at "GOVERNMENT WARNING" through the end of the sentence about \
  health problems (preserve case exactly). The warning block is almost always \
  part of the label artwork.

CRITICAL RULES (do not violate):
- Never copy a value that appears ONLY inside a form field, numbered item, \
  TTB header, email field, signature block, or "FORMULA" line into the "label" object.
- If a candidate value for a label field (especially alcohol_content, class_type, \
  brand_name) only shows up in the application/form section of the transcript \
  and does NOT appear independently in the label artwork / product design text, \
  set that field to null in "label".
- Concrete bad example (DO NOT REPEAT):
  If the transcript has "9. FORMULA 45% ACV" or "45% ACV" only in form-field lines, \
  put it in "application" only. Set "label"."alcohol_content" to null. Only put a \
  percentage in "label" if it appears as independent label artwork text (not inside \
  a numbered form field or TTB header).
- The model must look at the context around each occurrence (including the \
  === PAGE N VIEW M === markers) to decide provenance.
- Use null for anything not present in the appropriate section.

The transcript may contain repeated text because of overlapping views; \
  treat duplicates as a single occurrence and prefer the clearest rendering.

To help users easily compare the label artwork vs the form, also identify
which transcript segments belong to each source and output *only* the EXACT
marker strings (including the "=== PAGE N VIEW M ===" text) in these two arrays:

"label_markers": array of strings - the exact markers (e.g. "=== PAGE 1 VIEW 1 ===")
  for segments whose OCR text is predominantly the bottle label artwork / graphic
  design (large brand name, the GOVERNMENT WARNING block in its designed layout
  and typography, net contents styled as on the label, "BOTTLED BY" / "PRODUCED BY"
  in the label's font, etc.). List these first.

"form_markers": array of strings - the exact markers for segments whose OCR text
  is predominantly the typed application/form fields, numbered items (e.g. "9. ",
  "13. "), "FORMULA" declarations, "Brand Name:", "Alcohol Content:", signature
  blocks, TTB headers, "AUTHORIZED SIGNATURE...", "PLANT REGISTRY..." etc.

CRITICAL: The two arrays MUST BE DISJOINT. No marker string may appear in both.
Every marker that has meaningful text must be assigned to exactly one of the two
lists. Do not repeat or put the full set in both.

Do NOT output "raw_label_text", "raw_form_text", or any large transcript text
inside the JSON at all. Only the short marker identifier strings. The server
will reconstruct the separated display text from the original OCR transcripts
using the markers you provide.

Your entire response must be a single valid JSON object matching the schema.
No text before or after the JSON. Escape any special characters inside strings.

TRANSCRIPT:
{transcript}
"""

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "application": {
            "type": "object",
            "properties": {
                "brand_name": {"type": ["string", "null"]},
                "class_type": {"type": ["string", "null"]},
                "alcohol_content": {"type": ["string", "null"]},
                "net_contents": {"type": ["string", "null"]},
                "bottler": {"type": ["string", "null"]},
                "country_of_origin": {"type": ["string", "null"]},
            },
            "required": ["brand_name", "class_type", "alcohol_content",
                         "net_contents", "bottler", "country_of_origin"],
        },
        "label": {
            "type": "object",
            "properties": {
                "brand_name": {"type": ["string", "null"]},
                "class_type": {"type": ["string", "null"]},
                "alcohol_content": {"type": ["string", "null"]},
                "net_contents": {"type": ["string", "null"]},
                "bottler": {"type": ["string", "null"]},
                "country_of_origin": {"type": ["string", "null"]},
                "government_warning": {"type": ["string", "null"]},
            },
            "required": ["brand_name", "class_type", "alcohol_content",
                         "net_contents", "bottler", "country_of_origin",
                         "government_warning"],
        },
        "label_markers": {"type": ["array", "null"], "items": {"type": "string"}},
        "form_markers": {"type": ["array", "null"], "items": {"type": "string"}}
    },
    "required": ["application", "label"]
}


class LlmError(Exception):
    pass


def _loads_lenient(content, what):
    """json.loads tolerant of common LLM wrappers (code fences, chatter)."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*```$', '', text)
    # Try to isolate the first top-level JSON object if there's surrounding text
    if not text.startswith("{"):
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            text = m.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Include a snippet for debugging
        snippet = (content or "")[:300].replace("\n", "\\n")
        raise LlmError(f"{what} returned invalid JSON: {e} (near: {snippet}...)") from e


def cap_transcript(transcript, limit):
    """Cap transcript length while keeping BOTH ends: pages are joined in
    document order (form first, label artwork last), so a head-only cap
    would hide exactly the label text the analysis is about."""
    if len(transcript) <= limit:
        return transcript
    half = limit // 2
    return (transcript[:half]
            + "\n\n[... transcript truncated for model context ...]\n\n"
            + transcript[-half:])


def parse_extraction(content):
    data = _loads_lenient(content, "extraction")
    if "application" not in data or "label" not in data:
        raise LlmError("extraction JSON missing application/label keys")
    return data


def _post(url, payload, timeout, what):
    try:
        r = httpx.post(url, json=payload, timeout=timeout)
    except httpx.HTTPError as e:
        raise LlmError(f"{what} server unreachable at {url}: {e}") from e
    if r.status_code != 200:
        raise LlmError(f"{what} server error {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]


def ocr_page(png_bytes):
    b64 = base64.b64encode(png_bytes).decode()
    payload = {
        "model": "glm-ocr",
        "temperature": 0,
        "max_tokens": 3000,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": OCR_PROMPT},
            {"type": "image_url",
             "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ]}],
    }
    return _post(OCR_URL, payload, OCR_TIMEOUT, "OCR")


def extract_fields(transcript):
    payload = {
        "model": "qwen",
        "temperature": 0,
        "max_tokens": 3000,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "extract",
                                            "schema": EXTRACTION_SCHEMA}},
        "messages": [{"role": "user",
                      "content": EXTRACT_PROMPT.format(transcript=transcript)}],
    }
    return parse_extraction(_post(QWEN_URL, payload, QWEN_TIMEOUT, "extraction"))


# --- New: LLM-powered compliance analysis (broadened scope) ---

COMPLIANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "product_category": {
            "type": ["string", "null"],
            "description": "wine, distilled_spirits, malt_beverage, or unknown"
        },
        "overall_assessment": {
            "type": "string",
            "description": "Short summary: likely_compliant, issues_found, or needs_human_review"
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "citation": {"type": ["string", "null"]},
                    "status": {"type": "string", "enum": ["pass", "fail", "missing", "needs_review", "info"]},
                    "evidence": {"type": ["string", "null"]},
                    "notes": {"type": ["string", "null"]}
                },
                "required": ["requirement", "status"]
            }
        },
        "key_observations": {"type": ["string", "null"]}
    },
    "required": ["product_category", "overall_assessment", "findings"]
}


COMPLIANCE_PROMPT = """\
You are a careful, conservative TTB label compliance analyst. Your job is to \
analyze the OCR transcript of an OMB No. 1513-0020 (TTB F 5100.31) COLA \
submission and determine whether the submitted label artwork meets core \
federal labeling requirements.

Use ONLY the provided KNOWLEDGE section and the TRANSCRIPT. Quote verbatim \
evidence (preserve original capitalization and punctuation as much as \
possible). Do not invent rules or text that is not present. If OCR is unclear \
or evidence is missing/ambiguous, use status "needs_review" and quote what \
you see.

First, determine the primary product_category from the form declarations and \
label text (wine, distilled_spirits, malt_beverage, or unknown).

Then produce a list of findings for the major mandatory items:
- Health warning statement (use the exact statutory text and rules from KNOWLEDGE)
- Brand name
- Class and type designation
- Alcohol content (when required)
- Net contents
- Name and address / responsible party
- Country of origin (especially for imported products)
- Any other prominent issues you observe that conflict with the KNOWLEDGE \
  (misleading claims, missing required statements, etc.)

For the health warning, locate the best candidate text block and note it. \
(The deterministic code checker will also validate it strictly.)

Cross-reference the label artwork text against any declarations visible in \
the form portion of the transcript. Flag clear inconsistencies.

Output must be valid JSON matching the required schema. Include direct quotes \
in the "evidence" field for every finding.

KNOWLEDGE:
{knowledge}

TRANSCRIPT (full OCR of form + label artwork):
{transcript}

FORM CONTEXT (extracted declarations, may be partial or null):
{form_context}
"""


def parse_compliance(content: str) -> dict:
    """Parse and lightly validate the compliance analysis JSON from the LLM."""
    data = _loads_lenient(content, "compliance analysis")

    # Minimal shape check
    if "findings" not in data or not isinstance(data.get("findings"), list):
        raise LlmError("compliance JSON missing 'findings' array")

    # Ensure required top-level keys exist
    data.setdefault("product_category", None)
    data.setdefault("overall_assessment", "needs_human_review")
    data.setdefault("key_observations", None)

    return data


def analyze_compliance(
    transcript: str,
    form_data: dict | None = None,
    commodity_hint: str | None = None,
) -> dict:
    """Run LLM compliance analysis grounded in the local knowledge base.

    Returns a dict with product_category, overall_assessment, findings list, etc.
    The findings contain 'requirement', 'status', 'evidence' (verbatim quote),
    'citation', and 'notes'.
    """
    knowledge = load_knowledge()

    # Provide a compact form context so the model can cross-check declarations
    form_context = ""
    if form_data:
        try:
            form_context = json.dumps(form_data, ensure_ascii=False, indent=2)
        except Exception:
            form_context = str(form_data)

    if commodity_hint:
        form_context = f"Hint: primary commodity appears to be {commodity_hint}\n" + form_context

    user_content = COMPLIANCE_PROMPT.format(
        knowledge=knowledge,
        transcript=cap_transcript(transcript, 8000),  # context cap, keeps both ends
        form_context=form_context or "(no structured form data extracted)",
    )

    payload = {
        "model": "qwen",
        "temperature": 0,
        "max_tokens": 2000,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "compliance", "schema": COMPLIANCE_SCHEMA},
        },
        "messages": [{"role": "user", "content": user_content}],
    }

    raw = _post(QWEN_URL, payload, QWEN_TIMEOUT, "compliance_analysis")
    return parse_compliance(raw)
