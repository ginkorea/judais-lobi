# tests/test_result_paging.py — reading part of a result that is only text

"""`mission_result` can page a text-only result.

The gap lane N recorded, 18 August 2026: a 40 KB test log is bounded
head-and-tail in the transcript with a marker naming its store handle,
and `mission_result(handle="r7")` then answered with a *summary* — "3,871
characters of text" — because `path` walks a typed payload and a log has
none. There was no way to see the middle at all. The coding pack worked
round it by teaching the model to re-read files with `fs`, which is
content standing in for a harness property and no use whatever for a log
that was never a file.

Three readers, one rule each: `offset`/`limit` count characters,
`lines="A-B"` counts lines, `grep` returns matching lines with their
numbers. Every page is bounded by the store's own `_max_chars`, the same
cap a field read gets, because it is the same question — how much of one
result may be pasted back into a transcript that already bounded it once.

The tool DESCRIPTOR does not advertise these yet: the catalogue is the
system turn, the committed corpus is recorded against its bytes, and the
sentence that teaches a model to page lands with the re-recording. What
is asserted here is the capability and the executor's forwarding of it —
see `MissionResultStore.descriptor` for the text that is to be added.
"""

import pytest

from core.runtime.results import (
    DEFAULT_MATCHES,
    PAGING,
    BranchedStores,
    MissionResultStore,
    paging_of,
)

#: A test log: long enough to be bounded, structured enough to search.
LOG = "\n".join(
    [f"tests/test_thing.py::case_{n} PASSED" for n in range(1, 120)]
    + ["tests/test_thing.py::case_120 FAILED",
       "E   assert 3 == 4",
       "===== 119 passed, 1 failed in 2.31s ====="]
)


@pytest.fixture
def store():
    store = MissionResultStore()
    store.record("verify", {"action": "test"}, text=LOG, exit_code=1)
    return store


class TestTheDefaultReadersAreUntouched:
    """Nothing here changes what an existing call does."""

    def test_the_handle_alone_is_still_a_summary(self, store):
        rc, out, _err = store.read("r1")
        assert rc == 0
        assert out.startswith("r1: verify(action='test')")

    def test_no_handle_is_still_the_index(self, store):
        assert "r1: verify" in store.read()[1]

    def test_a_zero_offset_is_not_a_request(self, store):
        """`offset=0` is what every executor passes when the model wrote
        nothing; reading it as a request would turn the summary into a
        page of the first no characters."""
        assert store.read("r1", offset=0, limit=0)[1] == store.read("r1")[1]


class TestASliceOfCharacters:
    def test_it_returns_the_characters_asked_for(self, store):
        rc, out, _err = store.read("r1", offset=0, limit=40)
        assert rc == 0
        assert LOG[:40] in out

    def test_it_says_where_in_the_result_this_is(self, store):
        _rc, out, _err = store.read("r1", offset=100, limit=40)
        assert f"characters 100-140 of {len(LOG)}" in out

    def test_it_names_the_next_page(self, store):
        """A page that leaves the model no way to ask for the next one is
        the truncation marker's problem all over again."""
        _rc, out, _err = store.read("r1", offset=0, limit=40)
        assert 'mission_result(handle="r1", offset=40)' in out

    def test_the_last_page_promises_nothing(self, store):
        _rc, out, _err = store.read("r1", offset=len(LOG) - 10, limit=100)
        assert "Next page" not in out
        assert out.endswith(LOG[-10:])

    def test_a_string_offset_is_the_same_offset(self, store):
        """The JSON protocol hands a model's `"100"` through as written."""
        assert store.read("r1", offset="100", limit="40")[1] == \
            store.read("r1", offset=100, limit=40)[1]

    def test_a_page_is_bounded_by_the_stores_own_cap(self):
        """`limit` asks; the store answers with what a field read costs,
        says which characters those were, and names the next page — so a
        `limit` nobody may have is a page count and not a loss."""
        store = MissionResultStore(max_chars=200)
        store.record("verify", text="x" * 5_000)
        _rc, out, _err = store.read("r1", offset=0, limit=5_000)
        assert "characters 0-200 of 5000" in out
        assert 'offset=200' in out
        assert len(out) < 600

    def test_a_line_range_is_bounded_by_the_same_cap(self):
        """The other reader, the same limit, and it says it was cut —
        `lines` cannot be answered by moving the offset on."""
        store = MissionResultStore(max_chars=200)
        store.record("verify", text="\n".join("x" * 100 for _ in range(50)))
        _rc, out, _err = store.read("r1", lines="1-50")
        assert "cut at 200 characters" in out
        assert len(out) < 600

    def test_an_offset_past_the_end_says_how_long_it_is(self, store):
        rc, _out, err = store.read("r1", offset=len(LOG) + 1)
        assert rc == 1
        assert f"{len(LOG)} characters" in err

    def test_a_word_is_not_an_offset(self, store):
        rc, _out, err = store.read("r1", offset="soon")
        assert rc == 1
        assert "whole number" in err

    def test_a_negative_offset_is_refused_rather_than_wrapped(self, store):
        rc, _out, err = store.read("r1", offset=-50)
        assert rc == 1
        assert "counts forward" in err


class TestARangeOfLines:
    def test_it_returns_the_lines_inclusive_and_one_based(self, store):
        rc, out, _err = store.read("r1", lines="1-3")
        assert rc == 0
        assert "case_1 PASSED" in out and "case_3 PASSED" in out
        assert "case_4" not in out

    def test_one_number_is_one_line(self, store):
        _rc, out, _err = store.read("r1", lines="2")
        assert "case_2 PASSED" in out
        assert "case_3" not in out

    def test_an_open_range_runs_to_the_end(self, store):
        _rc, out, _err = store.read("r1", lines="121-")
        assert "119 passed, 1 failed" in out

    def test_it_says_which_lines_of_how_many(self, store):
        _rc, out, _err = store.read("r1", lines="1-3")
        assert f"lines 1-3 of {len(LOG.splitlines())}" in out

    def test_a_range_past_the_end_stops_at_the_end(self, store):
        rc, out, _err = store.read("r1", lines="120-9999")
        assert rc == 0
        assert out.startswith(f"r1: verify, lines 120-{len(LOG.splitlines())}")

    def test_a_first_line_past_the_end_is_refused(self, store):
        rc, _out, err = store.read("r1", lines="9999")
        assert rc == 1
        assert "past the end" in err

    def test_a_backwards_range_is_refused(self, store):
        rc, _out, err = store.read("r1", lines="40-12")
        assert rc == 1
        assert "ends before it begins" in err

    def test_line_zero_is_refused_rather_than_read_as_one(self, store):
        rc, _out, err = store.read("r1", lines="0-3")
        assert rc == 1
        assert "counts from 1" in err

    def test_a_shape_that_is_not_a_range_teaches_the_shape(self, store):
        rc, _out, err = store.read("r1", lines="the failing bit")
        assert rc == 1
        assert '12-40' in err


class TestSearchingTheText:
    def test_matching_lines_come_back_with_their_numbers(self, store):
        rc, out, _err = store.read("r1", grep="FAILED")
        assert rc == 0
        assert "120: tests/test_thing.py::case_120 FAILED" in out

    def test_it_says_how_many_matched(self, store):
        _rc, out, _err = store.read("r1", grep="PASSED")
        assert "40 of 119 lines matching" in out

    def test_the_matches_are_bounded_and_say_so(self, store):
        _rc, out, _err = store.read("r1", grep="PASSED")
        assert len(out.splitlines()) <= DEFAULT_MATCHES + 3
        assert "more matching lines" in out

    def test_limit_bounds_the_matches(self, store):
        _rc, out, _err = store.read("r1", grep="PASSED", limit=3)
        assert "3 of 119 lines matching" in out

    def test_no_match_is_an_answer_and_not_an_error(self, store):
        """"Nothing in the log says that" is something the model needs to
        know, and a non-zero exit reads as a broken tool."""
        rc, out, _err = store.read("r1", grep="SegmentationFault")
        assert rc == 0
        assert "no line of" in out

    def test_an_unusable_regex_says_so(self, store):
        rc, _out, err = store.read("r1", grep="case_(")
        assert rc == 1
        assert "not a usable regular expression" in err


class TestTheTwoReadersDoNotCompose:
    """A precedence rule nobody can see from the outside is worse than a
    refusal: a model that asked for a field and got a slice of the
    rendered text would quote the slice."""

    def test_a_path_and_a_page_in_one_call_is_refused(self):
        store = MissionResultStore()
        store.record("mcp.view", text="rendered", evidence='{"total": 7}')
        rc, _out, err = store.read("r1", path="total", offset=5)
        assert rc == 1
        assert "two readers" in err

    def test_lines_and_offset_in_one_call_is_refused(self, store):
        rc, _out, err = store.read("r1", lines="1-3", offset=5)
        assert rc == 1
        assert "one counts lines and the other counts characters" in err

    def test_grep_and_lines_in_one_call_is_refused(self, store):
        rc, _out, err = store.read("r1", grep="FAILED", lines="1-3")
        assert rc == 1
        assert "`grep` searches the whole text" in err

    def test_a_result_with_no_text_says_what_it_has(self):
        store = MissionResultStore()
        store.record("mcp.view", text="", evidence='{"total": 7}')
        rc, _out, err = store.read("r1", lines="1")
        assert rc == 1
        assert "no text to page" in err


class TestTheArgumentsReachTheStore:
    """Three callers spell these four names; `paging_of` is the one that
    knows them, so none of them can stop carrying one."""

    def test_the_filter_takes_the_four_and_nothing_else(self):
        assert paging_of({"offset": 3, "branch": "s2", "nonsense": 1}) == \
            {"offset": 3}

    def test_every_paging_name_reaches_read(self, store):
        for name in PAGING:
            assert paging_of({name: "1"}) == {name: "1"}

    def test_the_executor_forwards_them(self, store):
        rc, out, _err = store.executor()(handle="r1", lines="2")
        assert rc == 0
        assert "case_2 PASSED" in out

    def test_the_executor_still_ignores_what_it_does_not_know(self, store):
        """The loop adds `branch` after the schema check, and a model can
        write anything at all."""
        rc, _out, _err = store.executor()(handle="r1", nonsense=True)
        assert rc == 0

    def test_a_branched_store_forwards_them_to_the_right_child(self):
        """A staged turn's children each keep their own results, and a
        page of one child's log must not be served from a sibling's."""
        class FakeBus:
            def __init__(self):
                self.registered = {}

            def get_descriptor(self, name):
                return None

            def register(self, descriptor, executor):
                self.registered[descriptor.tool_name] = executor

            def unregister(self, name):
                self.registered.pop(name, None)

        branched = BranchedStores()
        bus = FakeBus()
        for branch, body in (("s1", "one\ntwo"), ("s2", "three\nfour")):
            store = MissionResultStore()
            store.record("verify", text=body)
            branched.open(bus, "mission_result", branch, store)

        rc, out, _err = branched._read(handle="r1", lines="2", branch="s2")
        assert rc == 0
        assert "four" in out
