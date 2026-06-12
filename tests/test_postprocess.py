from server.postprocess import is_form_line, postprocess_extraction

FORM_SEGMENT = (
    "=== PAGE 1 VIEW 1 ===\n"
    "APPLICATION FOR CERTIFICATION\n"
    "6. BRAND NAME CIES\n"
    "9. FORMULA 45% ACV\n"
    "13. EMAIL ADDRESS someone@example.com"
)
LABEL_SEGMENT = (
    "=== PAGE 1 VIEW 2 ===\n"
    "CIES 2013\n"
    "RED WINE\n"
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL ..."
)
TRANSCRIPTS = [FORM_SEGMENT, LABEL_SEGMENT]
JOINED = "\n\n".join(TRANSCRIPTS)


def make_extraction(**over):
    ext = {
        "application": {"brand_name": None, "alcohol_content": None},
        "label": {"brand_name": "CIES", "alcohol_content": None,
                  "government_warning": None},
    }
    ext.update(over)
    return ext


def test_is_form_line():
    assert is_form_line("9. FORMULA 45% ACV")
    assert is_form_line("AUTHORIZED SIGNATURE, ALCOHOL AND TOBACCO TAX")
    assert not is_form_line("CIES 2013")


def test_marker_split_used_when_disjoint():
    ext = make_extraction(label_markers=["=== PAGE 1 VIEW 2 ==="],
                          form_markers=["=== PAGE 1 VIEW 1 ==="])
    postprocess_extraction(ext, TRANSCRIPTS, JOINED)
    assert "CIES 2013" in ext["raw_label_text"]
    assert "FORMULA" not in ext["raw_label_text"]
    assert "FORMULA" in ext["raw_form_text"]


def test_fallback_split_when_markers_duplicated():
    """The model often returns the full marker set in BOTH lists; the
    deterministic line-based fallback must still produce a real split."""
    both = ["=== PAGE 1 VIEW 1 ===", "=== PAGE 1 VIEW 2 ==="]
    ext = make_extraction(label_markers=list(both), form_markers=list(both))
    postprocess_extraction(ext, TRANSCRIPTS, JOINED)
    rl, rf = ext["raw_label_text"], ext["raw_form_text"]
    assert rl and rf and rl != rf
    assert "FORMULA" in rf
    assert "FORMULA" not in rl
    assert "CIES 2013" in rl


def test_fallback_split_when_no_markers():
    ext = make_extraction()
    postprocess_extraction(ext, TRANSCRIPTS, JOINED)
    assert "FORMULA" in ext["raw_form_text"]
    assert "CIES 2013" in ext["raw_label_text"]


def test_leakage_guard_nulls_form_only_abv():
    """A value seen only in form-field lines must not be claimed as label art."""
    ext = make_extraction()
    ext["application"]["alcohol_content"] = "45% ACV"
    ext["label"]["alcohol_content"] = "45% ACV"  # only occurs in '9. FORMULA…'
    postprocess_extraction(ext, TRANSCRIPTS, JOINED)
    assert ext["label"]["alcohol_content"] is None


def test_leakage_guard_nulls_when_application_missing():
    """Even if application field is None, a label value that does not appear
    in the separated label-artwork text must be nullified."""
    ext = make_extraction()
    ext["label"]["alcohol_content"] = "45% ACV"  # only in form lines
    postprocess_extraction(ext, TRANSCRIPTS, JOINED)
    assert ext["label"]["alcohol_content"] is None


def test_leakage_guard_keeps_abv_printed_on_label():
    transcripts = [FORM_SEGMENT,
                   LABEL_SEGMENT + "\nALC. 45% ACV BY VOL."]
    joined = "\n\n".join(transcripts)
    ext = make_extraction()
    ext["application"]["alcohol_content"] = "45% ACV"
    ext["label"]["alcohol_content"] = "45% ACV"
    postprocess_extraction(ext, transcripts, joined)
    # Present on an artwork line that is NOT form-flagged -> keep it.
    assert ext["label"]["alcohol_content"] == "45% ACV"


def test_backfill_brand_from_form_declaration():
    """Brand missing from 'application' but declared on a form line -> backfill."""
    ext = make_extraction()
    postprocess_extraction(ext, TRANSCRIPTS, JOINED)
    assert ext["application"]["brand_name"] == "CIES"


def test_no_backfill_when_brand_only_on_label_artwork():
    """If the brand appears ONLY as label artwork, application.brand_name must
    stay empty so the verdict reports 'missing' instead of a fake 'match'."""
    transcripts = ["=== PAGE 1 VIEW 1 ===\n9. FORMULA 45% ACV", LABEL_SEGMENT]
    joined = "\n\n".join(transcripts)
    ext = make_extraction()
    postprocess_extraction(ext, transcripts, joined)
    assert ext["application"]["brand_name"] is None
