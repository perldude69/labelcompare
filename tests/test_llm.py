import pytest

from server.llm import (LlmError, cap_transcript, parse_compliance,
                        parse_extraction)


def test_parse_extraction_valid():
    content = '{"application": {"brand_name": "X"}, "label": {"brand_name": "Y"}}'
    out = parse_extraction(content)
    assert out["application"]["brand_name"] == "X"


def test_parse_extraction_invalid_json():
    with pytest.raises(LlmError):
        parse_extraction("not json {")


def test_parse_extraction_missing_keys():
    with pytest.raises(LlmError):
        parse_extraction('{"foo": 1}')


def test_parse_extraction_strips_code_fence():
    content = '```json\n{"application": {}, "label": {}}\n```'
    assert parse_extraction(content) == {"application": {}, "label": {}}


def test_parse_compliance_valid():
    out = parse_compliance('{"findings": [], "product_category": "wine",'
                           ' "overall_assessment": "likely_compliant"}')
    assert out["findings"] == []
    assert out["key_observations"] is None  # defaulted


def test_parse_compliance_strips_code_fence():
    content = ('```json\n{"findings": [], "product_category": null,'
               ' "overall_assessment": "x"}\n```')
    assert parse_compliance(content)["findings"] == []


def test_parse_compliance_missing_findings():
    with pytest.raises(LlmError):
        parse_compliance('{"product_category": "wine"}')


def test_cap_transcript_short_passthrough():
    assert cap_transcript("abc", 100) == "abc"


def test_cap_transcript_keeps_head_and_tail():
    """Label pages come LAST in the joined transcript; a blind head-only cap
    hides them from the compliance model. The cap must keep both ends."""
    s = "HEAD-" + ("x" * 10000) + "-GOVERNMENT WARNING TAIL"
    capped = cap_transcript(s, 4000)
    assert len(capped) < len(s)
    assert capped.startswith("HEAD-")
    assert capped.endswith("-GOVERNMENT WARNING TAIL")
    assert "truncated" in capped
