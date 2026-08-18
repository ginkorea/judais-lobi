from index import build, lookup


def test_lookup_ignores_case_and_padding():
    table = build(["  Alice ", "BOB"])
    assert lookup(table, "alice") == "  Alice "
    assert lookup(table, "bob") == "BOB"


def test_lookup_reports_a_missing_name_as_none():
    assert lookup(build(["Alice"]), "carol") is None
