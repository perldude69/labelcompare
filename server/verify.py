"""Pure verification logic. No I/O, no LLM calls."""
import re

# 27 CFR 16.21 statutory warning text.
STATUTORY_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women "
    "should not drink alcoholic beverages during pregnancy because of the "
    "risk of birth defects. (2) Consumption of alcoholic beverages impairs "
    "your ability to drive a car or operate machinery, and may cause "
    "health problems."
)

REQUIRED_FIELDS = ("brand_name", "alcohol_content", "government_warning")
INFO_FIELDS = ("class_type", "net_contents", "bottler", "country_of_origin")


def normalize(s):
    """Lowercase, drop punctuation, collapse whitespace."""
    if s is None:
        return ""
    s = re.sub(r"[^a-z0-9% ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def parse_abv(s):
    """First percentage-like number in the string, else a bare number."""
    if s is None:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
    if not m:
        m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", s)
    return float(m.group(1)) if m else None


def brands_match(form_brand, label_brand):
    """Case-insensitive; allows containment either way (label often adds
    vintage/varietal around the brand name)."""
    a, b = normalize(form_brand), normalize(label_brand)
    if not a or not b:
        return False
    return a in b or b in a


def check_warning(warning):
    """The only case-sensitive check in the app."""
    result = {"present": False, "content_ok": False, "caps_ok": False,
              "ok": False, "text": warning}
    if not warning or not warning.strip():
        return result
    result["present"] = True
    # Extraction often includes adjacent label lines; judge only the span
    # from "GOVERNMENT WARNING" through "HEALTH PROBLEMS."
    m = re.search(r"government\s+warning.*?health\s+problems\s*\.?",
                  warning, re.IGNORECASE | re.DOTALL)
    candidate = m.group(0) if m else warning
    # Content: compare normalized (case-insensitive) against statutory text.
    result["content_ok"] = normalize(candidate) == normalize(STATUTORY_WARNING)
    # Caps: every letter in the warning must be uppercase.
    result["caps_ok"] = candidate == candidate.upper()
    result["ok"] = result["content_ok"] and result["caps_ok"]
    return result


def _field(form_val, label_val, matched):
    if matched:
        status = "match"
    elif form_val and label_val:
        status = "mismatch"
    else:
        status = "missing"
    return {"application": form_val, "label": label_val, "status": status}


def verdict(application, label):
    """Compare extracted application-form fields against label fields."""
    application = application or {}
    label = label or {}
    fields = {}

    fields["brand_name"] = _field(
        application.get("brand_name"), label.get("brand_name"),
        brands_match(application.get("brand_name"), label.get("brand_name")))

    form_abv = parse_abv(application.get("alcohol_content"))
    label_abv = parse_abv(label.get("alcohol_content"))
    fields["alcohol_content"] = _field(
        application.get("alcohol_content"), label.get("alcohol_content"),
        form_abv is not None and form_abv == label_abv)

    w = check_warning(label.get("government_warning"))
    fields["government_warning"] = {
        "application": "(required by 27 CFR 16.21)",
        "label": label.get("government_warning"),
        "status": "match" if w["ok"] else ("missing" if not w["present"]
                                           else "mismatch"),
        "detail": w,
    }

    # Informational fields: shown in the UI, never affect pass/fail.
    for name in INFO_FIELDS:
        fv, lv = application.get(name), label.get(name)
        if fv and lv:
            matched = normalize(fv) == normalize(lv) or brands_match(fv, lv)
            fields[name] = _field(fv, lv, matched)
        else:
            fields[name] = {"application": fv, "label": lv, "status": "info"}

    passed = all(fields[f]["status"] == "match" for f in REQUIRED_FIELDS)
    return {"passed": passed, "fields": fields}
