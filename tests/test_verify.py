from server.verify import (
    parse_abv, normalize, brands_match, check_warning, verdict,
)

GOOD_WARNING = (
    "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL, WOMEN "
    "SHOULD NOT DRINK ALCOHOLIC BEVERAGES DURING PREGNANCY BECAUSE OF THE "
    "RISK OF BIRTH DEFECTS. (2) CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS "
    "YOUR ABILITY TO DRIVE A CAR OR OPERATE MACHINERY, AND MAY CAUSE "
    "HEALTH PROBLEMS."
)


def test_parse_abv():
    assert parse_abv("ALC. 12.5% BY VOL") == 12.5
    assert parse_abv("40% ALC/VOL") == 40.0
    assert parse_abv("12.5") == 12.5
    assert parse_abv(None) is None
    assert parse_abv("no number here") is None


def test_normalize():
    assert normalize("  CIES   2013 ") == "cies 2013"
    assert normalize("Smirnoff!") == "smirnoff"


def test_brands_match_case_insensitive():
    assert brands_match("CIES", "Cies")
    assert brands_match("CIES", "CIES 2013 100% ALBARINO")  # containment
    assert not brands_match("CIES", "SMIRNOFF")
    assert not brands_match(None, "CIES")


def test_check_warning_good():
    r = check_warning(GOOD_WARNING)
    assert r["present"] and r["content_ok"] and r["caps_ok"]
    assert r["ok"]


def test_check_warning_lowercase_body_fails_caps():
    bad = GOOD_WARNING.replace("WOMEN", "women")
    r = check_warning(bad)
    assert r["present"] and r["content_ok"] and not r["caps_ok"]
    assert not r["ok"]


def test_check_warning_missing_clause_fails_content():
    bad = GOOD_WARNING[:80]
    r = check_warning(bad)
    assert not r["content_ok"] and not r["ok"]


def test_check_warning_absent():
    r = check_warning(None)
    assert not r["present"] and not r["ok"]


def test_verdict_pass():
    application = {"brand_name": "CIES", "alcohol_content": "12.5%",
                   "class_type": "TABLE WHITE WINE", "net_contents": "750ML",
                   "bottler": "RODRIGO MENDEZ", "country_of_origin": "SPAIN"}
    label = {"brand_name": "Cies 2013", "alcohol_content": "ALC. 12.5% BY VOL.",
             "net_contents": "750ML", "government_warning": GOOD_WARNING}
    v = verdict(application, label)
    assert v["passed"] is True
    assert v["fields"]["brand_name"]["status"] == "match"
    assert v["fields"]["alcohol_content"]["status"] == "match"
    assert v["fields"]["government_warning"]["status"] == "match"


def test_verdict_fail_abv_mismatch():
    v = verdict({"brand_name": "X", "alcohol_content": "40%"},
                {"brand_name": "X", "alcohol_content": "37.5%",
                 "government_warning": GOOD_WARNING})
    assert v["passed"] is False
    assert v["fields"]["alcohol_content"]["status"] == "mismatch"


def test_verdict_missing_required_field():
    v = verdict({"brand_name": "X", "alcohol_content": "40%"},
                {"brand_name": None, "alcohol_content": "40%",
                 "government_warning": GOOD_WARNING})
    assert v["passed"] is False
    assert v["fields"]["brand_name"]["status"] == "missing"
