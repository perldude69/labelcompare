"""Clients for the local llama.cpp servers."""
import base64
import json
import os

import httpx

OCR_URL = os.environ.get("OCR_URL", "http://127.0.0.1:8090/v1/chat/completions")
QWEN_URL = os.environ.get("QWEN_URL", "http://127.0.0.1:8080/v1/chat/completions")
OCR_TIMEOUT = 240
QWEN_TIMEOUT = 180

OCR_PROMPT = (
    "Transcribe all text in this image exactly as printed. Preserve "
    "capitalization and punctuation. Output only the transcribed text."
)

EXTRACT_PROMPT = """\
The text below is an OCR transcript of a TTB COLA alcohol label application. \
It contains APPLICATION FORM data (typed form fields such as brand name, \
class/type, alcohol content, net contents, bottler name/address, country of \
origin) and, usually after a phrase like "AFFIX COMPLETE SET OF LABELS", the \
text printed on the LABEL itself.

Extract two groups:
- "application": values from the form fields.
- "label": values exactly as printed on the label artwork, preserving the \
exact capitalization from the transcript. For "government_warning", copy the \
full warning verbatim starting at "GOVERNMENT WARNING" through the end of \
the sentence about health problems; preserve every character's case exactly.

Use null for anything not present.

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
    },
    "required": ["application", "label"],
}


class LlmError(Exception):
    pass


def parse_extraction(content):
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise LlmError(f"extraction returned invalid JSON: {e}") from e
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
             "image_url": {"url": "data:image/png;base64," + b64}},
        ]}],
    }
    return _post(OCR_URL, payload, OCR_TIMEOUT, "OCR")


def extract_fields(transcript):
    payload = {
        "model": "qwen",
        "temperature": 0,
        "max_tokens": 1200,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "extract",
                                            "schema": EXTRACTION_SCHEMA}},
        "messages": [{"role": "user",
                      "content": EXTRACT_PROMPT.format(transcript=transcript)}],
    }
    return parse_extraction(_post(QWEN_URL, payload, QWEN_TIMEOUT, "extraction"))
