import pytest

from server.llm import parse_extraction, LlmError


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
