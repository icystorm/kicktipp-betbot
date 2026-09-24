from helper.match import Match


def test_match_accepts_comma_decimal_odds():
    match = Match(
        "Home",
        "Away",
        "09.10.26 20:30",
        "1,61",
        "3,80",
        "5.02",
    )

    assert match.odds == (1.61, 3.8, 5.02)


def test_match_setters_accept_comma_decimal_odds():
    match = Match("Home", "Away", "09.10.26 20:30", "1.0", "2.0", "3.0")

    match.rate_home = "1,09"
    match.rate_deuce = "7,8"
    match.rate_road = "1,2"

    assert match.odds == (1.09, 7.8, 1.2)