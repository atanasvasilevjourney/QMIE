from levier.hl_symbols import venue_tag


def test_btc_is_hl():
    assert venue_tag("BTCUSDT") == "HL"


def test_random_not_hl():
    assert venue_tag("FOOBARUSDT") == ""
