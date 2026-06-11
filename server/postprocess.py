"""Deterministic post-processing of the LLM extraction output.

The extraction model is unreliable in three known ways; each gets a
code-level repair here so the rest of the pipeline can trust the data:

1. It returns marker lists for the label/form transcript split, but often
   puts the full marker set in BOTH lists -> reconstruct/split here.
2. It copies application-form values (e.g. "45% ACV" from a numbered form
   field) into the "label" object -> strip that leakage.
3. It attributes the brand only to "label" even when the form declares the
   same brand -> backfill, but ONLY when the value provably appears in a
   form-context line (a tautological transcript-wide check would turn real
   form/label mismatches into fake matches).
"""
import logging
import re

log = logging.getLogger(__name__)

# Lines that belong to the application form rather than the label artwork.
FORM_LINE_RE = re.compile(
    r"FORMULA|AUTHORIZED SIGNATURE|ALCOHOL AND TOBACCO TAX"
    r"|EMAIL ADDRESS|^\s*\d+\.\s|APPLICATION",
    re.IGNORECASE,
)

# Label fields whose value must actually be printed on the artwork.
LEAKAGE_KEYS = ("alcohol_content",)
# Fields that normally appear on both the form and the artwork.
BACKFILL_KEYS = ("brand_name", "bottler")


def is_form_line(line: str) -> bool:
    return bool(FORM_LINE_RE.search(line))


def _split_by_form_lines(joined_transcript: str):
    """Deterministic line-based split: (form_text, label_text)."""
    form_lines, label_lines = [], []
    for line in joined_transcript.splitlines(keepends=True):
        (form_lines if is_form_line(line) else label_lines).append(line)
    return "".join(form_lines) or None, "".join(label_lines) or None


def _split_by_markers(transcripts, extraction):
    """Join transcript segments per the model's marker lists.

    Returns (label_text, form_text); either may be None if the lists were
    missing or useless.
    """
    markers_to_text = {}
    for t in transcripts:
        first = t.split("\n", 1)[0].strip()  # segments start with their marker
        markers_to_text[first] = t

    def join(markers):
        parts = []
        for m in markers or []:
            if m in markers_to_text:
                parts.append(markers_to_text[m])
            else:  # tolerant match for slightly mangled markers
                hit = next((v for k, v in markers_to_text.items()
                            if m in k or k in m), None)
                if hit:
                    parts.append(hit)
        return "\n\n".join(parts) if parts else None

    lm = extraction.get("label_markers") or extraction.get("raw_label_markers")
    fm = extraction.get("form_markers") or extraction.get("raw_form_markers")
    if not lm and not fm:
        return None, None
    # The model tends to return the full set in both lists; keep first
    # occurrence on the label side, drop duplicates from the form side.
    lm_list = list(dict.fromkeys(lm or []))
    fm_list = [m for m in (fm or []) if m not in set(lm_list)]
    return join(lm_list), join(fm_list)


def reconstruct_raw_texts(extraction, transcripts, joined_transcript):
    """Set extraction['raw_label_text'/'raw_form_text'] for the UI."""
    label_text, form_text = _split_by_markers(transcripts, extraction)
    # Fall back to the deterministic split whenever the marker split failed
    # to produce two distinct non-empty blocks (covers the common case where
    # marker duplication left one side empty).
    if not label_text or not form_text or label_text == form_text:
        form_text, label_text = _split_by_form_lines(joined_transcript)
    extraction["raw_label_text"] = label_text
    extraction["raw_form_text"] = form_text


def strip_form_leakage(extraction, joined_transcript):
    """Null label values that only ever appear inside form-context lines."""
    application = extraction.get("application") or {}
    label = extraction.get("label") or {}
    lines = joined_transcript.splitlines()
    for key in LEAKAGE_KEYS:
        val = label.get(key)
        if not (val and application.get(key)):
            continue
        val_str = str(val).strip().lower()
        occurrences = [ln for ln in lines if val_str in ln.lower()]
        if occurrences and all(is_form_line(ln) for ln in occurrences):
            label[key] = None
    extraction["label"] = label


def backfill_application(extraction, joined_transcript):
    """Copy a label value into a missing application field ONLY when the
    transcript shows the value inside a form-context line (i.e. the form
    really declares it too). Never backfill from artwork-only text: a
    missing form declaration must surface as 'missing', not a fake match."""
    application = extraction.get("application") or {}
    label = extraction.get("label") or {}
    form_lines = [ln for ln in joined_transcript.splitlines()
                  if is_form_line(ln)]
    for key in BACKFILL_KEYS:
        if application.get(key) or not label.get(key):
            continue
        val_str = str(label[key]).strip().lower()
        if val_str and any(val_str in ln.lower() for ln in form_lines):
            application[key] = label[key]
    extraction["application"] = application


def postprocess_extraction(extraction, transcripts, joined_transcript):
    """Run all repairs in place. Reconstruction is best-effort (display
    only); the field-level guards are load-bearing and may raise."""
    try:
        reconstruct_raw_texts(extraction, transcripts, joined_transcript)
    except Exception:
        log.exception("raw-text reconstruction failed; UI will fall back "
                      "to the unsplit transcripts")
    strip_form_leakage(extraction, joined_transcript)
    backfill_application(extraction, joined_transcript)
    return extraction
