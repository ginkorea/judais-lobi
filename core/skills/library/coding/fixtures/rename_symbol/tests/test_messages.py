from greet import greeting
from report import report
from util import fmt_msg


def test_the_helper_brackets_the_subject():
    assert fmt_msg("subject", "body") == "[subject] body"


def test_greeting_uses_the_helper():
    assert greeting("ada") == "[greeting] hello, ada"


def test_report_uses_the_helper():
    assert report([1, 2, 3]) == "[report] 3 row(s)"
