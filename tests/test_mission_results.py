# tests/test_mission_results.py — the per-mission result store and its tool

"""What a mission's tools returned, kept whole and addressable.

The store exists so that bounding a tool result in the transcript is not
the same as losing it. Two things therefore have to hold: the full text
survives, and a model can reach one field of a structured payload
without holding the whole payload.
"""

import json

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.results import (
    RESULT_TOOL,
    MissionResultStore,
    ResultStoreConflict,
    StoredResult,
)
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor

VIEW = {
    "run_id": "run.5f21",
    "actors": [
        {"handle": "a.001", "score": 0.91, "records": ["rec.11", "rec.12"]},
        {"handle": "a.002", "score": 0.44, "records": ["rec.13"]},
    ],
    "totals": {"records": 12481, "blocks": 7},
}


@pytest.fixture
def store():
    return MissionResultStore()


@pytest.fixture
def loaded(store):
    store.record("mcp.runs_get", {"run_id": "run.5f21"},
                 text="a rendering for a human",
                 evidence=json.dumps(VIEW))
    return store


@pytest.fixture
def bus():
    return ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=["*"])))


class TestRecording:
    def test_handles_are_short_and_sequential(self, store):
        assert store.record("t", text="one").handle == "r1"
        assert store.record("t", text="two").handle == "r2"

    def test_the_full_text_is_kept_however_long(self, store):
        body = "x" * 500_000
        stored = store.record("t", text=body)
        assert store.get(stored.handle).text == body

    def test_the_structured_payload_survives_beside_the_text(self, loaded):
        assert loaded.get("r1").structured["totals"]["records"] == 12481

    def test_a_result_is_frozen(self, loaded):
        with pytest.raises(Exception):
            loaded.get("r1").text = "rewritten"

    def test_clear_starts_a_new_mission(self, loaded):
        loaded.clear()
        assert len(loaded) == 0
        assert loaded.record("t", text="x").handle == "r1"

    def test_unparseable_evidence_is_none_not_a_crash(self, store):
        store.record("t", text="x", evidence="{not json")
        assert store.get("r1").structured is None


class TestReadingAField:
    def test_a_dotted_path(self, loaded):
        assert loaded.read("r1", "totals.records") == (0, "12481", "")

    def test_an_indexed_path(self, loaded):
        code, out, _err = loaded.read("r1", "actors[0].handle")
        assert (code, out) == (0, "a.001")

    def test_a_nested_index(self, loaded):
        assert loaded.read("r1", "actors[1].records[0]")[1] == "rec.13"

    def test_a_negative_index(self, loaded):
        assert loaded.read("r1", "actors[-1].handle")[1] == "a.002"

    def test_an_object_comes_back_as_json(self, loaded):
        assert json.loads(loaded.read("r1", "totals")[1]) == VIEW["totals"]

    def test_one_field_is_far_smaller_than_the_payload(self, loaded):
        """The whole point: fetch a field, not two hundred kilobytes."""
        whole = len(json.dumps(VIEW))
        assert len(loaded.read("r1", "totals.records")[1]) < whole / 10


class TestReadingRefusals:
    def test_an_unknown_handle_lists_the_real_ones(self, loaded):
        code, _out, err = loaded.read("r9", "totals")
        assert code == 1
        assert "r1" in err

    def test_a_missing_field_names_what_was_there(self, loaded):
        code, _out, err = loaded.read("r1", "totalz")
        assert code == 1
        assert "totals" in err

    def test_an_index_out_of_range_says_how_many_there_are(self, loaded):
        code, _out, err = loaded.read("r1", "actors[9]")
        assert code == 1
        assert "2 items" in err

    def test_indexing_a_non_array(self, loaded):
        assert loaded.read("r1", "totals[0]")[0] == 1

    def test_a_field_of_a_result_with_no_payload(self, store):
        store.record("t", text="plain text only")
        code, _out, err = store.read("r1", "anything")
        assert code == 1
        assert "no structured payload" in err

    def test_a_text_only_result_is_read_by_page_instead(self, store):
        """The other half of the refusal above, and the reason it is not
        a dead end: `path` walks a payload and a log has none, so the
        text is read by page. The reader is
        `tests/test_result_paging.py`; this is the seam between them."""
        store.record("t", text="one\ntwo\nthree")
        assert "two" in store.read("r1", lines="2")[1]

    def test_no_handle_lists_what_is_stored(self, loaded):
        code, out, _err = loaded.read()
        assert code == 0
        assert "r1" in out and "mcp.runs_get" in out

    def test_a_handle_with_no_path_summarises_without_dumping(self, loaded):
        out = loaded.read("r1")[1]
        assert "run_id" in out
        assert "12481" not in out

    def test_a_returned_field_is_itself_bounded(self):
        small = MissionResultStore(max_chars=100)
        small.record("t", text="x", evidence=json.dumps({"blob": "y" * 5000}))
        out = small.read("r1", "blob")[1]
        assert "field truncated" in out
        assert len(out) < 400


class TestEvidenceForGrounding:
    def test_text_and_payload_both_count(self, loaded):
        evidence = loaded.evidence_texts()
        assert any("a rendering" in e for e in evidence)
        assert any("rec.11" in e for e in evidence)

    def test_a_refused_call_is_not_evidence(self, store):
        """A call that never reached a tool established nothing.

        ``-1`` is the bus's own number for that: an unknown tool name, a
        capability denial, an exception inside dispatch. What those carry
        is this harness's words about why it said no, and an identifier
        that appears only there is not grounded by it.
        """
        store.record("t", text="", evidence="", exit_code=-1)
        store.record("t", text="asset.1234", exit_code=-1)
        assert store.evidence_texts() == []

    def test_a_failed_verify_is_evidence_because_verify_says_so(self, store):
        """The one tool whose failure is its answer.

        A failing test suite has not failed to produce a result. This
        filtered on ``exit_code == 0`` until the coding pack, and an agent
        reporting "1 failed, 1 passed before the change" was quoting a
        result the validator had thrown away — so a true sentence came
        back ungrounded and the repair turn deleted it.
        """
        store.record("verify", text="1 failed, 1 passed in 0.04s",
                     exit_code=1)
        assert store.evidence_texts() == ["1 failed, 1 passed in 0.04s"]

    def test_a_bridged_verify_carries_the_same_declaration(self, store):
        """Matched with ``same_tool``, like every other name comparison
        in this harness: a server's ``verify`` under the bridge's
        namespace is that tool under a namespace."""
        store.record("mcp.verify", text="2 failed in 0.1s", exit_code=1)
        assert store.evidence_texts() == ["2 failed in 0.1s"]

    def test_another_tool_that_failed_is_not_evidence(self, store):
        """And the default stays the careful one.

        `mcp.run_code` crashing and printing a traceback computed
        nothing, and a figure lifted out of that traceback is the
        plausible fabrication `test_grounding_code_is_not_a_claim.py`
        refuses. Only a tool that DECLARES
        `failure_is_a_result` is read on failure.
        """
        store.record("mcp.run_code",
                     text="Traceback: gradient was 3.1416", exit_code=1)
        store.record("patch", text='{"success": false}', exit_code=1)
        assert store.evidence_texts() == []

    def test_a_failed_result_is_still_not_a_success(self, store):
        """Widening the evidence did not widen anything else.

        ``succeeded`` is what the rendering and the store's own index
        read; ``ran`` is the separate question of whether a tool was
        reached at all.
        """
        stored = store.record("verify", text="1 failed", exit_code=1)
        assert stored.ran is True
        assert stored.succeeded is False


class TestTheBusTool:
    def test_it_registers_and_dispatches(self, loaded, bus):
        loaded.register_on(bus)
        result = bus.dispatch(RESULT_TOOL, handle="r1", path="totals.blocks")
        assert result.exit_code == 0
        assert result.stdout == "7"

    def test_its_descriptor_carries_a_schema(self, loaded, bus):
        loaded.register_on(bus)
        assert "handle" in bus.get_descriptor(RESULT_TOOL).input_schema["properties"]

    def test_it_needs_no_scope_because_it_reaches_nothing(self, loaded):
        gated = ToolBus(capability_engine=CapabilityEngine(PolicyPack(allowed_scopes=[])))
        loaded.register_on(gated)
        assert gated.dispatch(RESULT_TOOL, handle="r1", path="run_id").exit_code == 0

    def test_it_refuses_to_shadow_an_existing_tool(self, loaded, bus):
        bus.register(ToolDescriptor(tool_name=RESULT_TOOL), lambda **_kw: (0, "mine", ""))
        with pytest.raises(ResultStoreConflict):
            loaded.register_on(bus)
        assert bus.dispatch(RESULT_TOOL).stdout == "mine"

    def test_it_can_be_registered_under_another_name(self, loaded, bus):
        loaded.register_on(bus, "peek")
        assert bus.dispatch("peek", handle="r1", path="run_id").stdout == "run.5f21"


class TestTheBusCarriesEvidence:
    """A four-element executor return reaches ``ToolResult.evidence``.

    Without this the structured payload dies at the bus boundary and the
    store can only ever hold the rendering.
    """

    def test_a_four_tuple_populates_evidence(self, bus):
        bus.register(
            ToolDescriptor(tool_name="typed"),
            lambda **_kw: (0, "rendered", "", '{"n": 1}'),
        )
        assert bus.dispatch("typed").evidence == '{"n": 1}'

    def test_a_three_tuple_still_works(self, bus):
        bus.register(ToolDescriptor(tool_name="plain"), lambda **_kw: (0, "out", ""))
        result = bus.dispatch("plain")
        assert (result.stdout, result.evidence) == ("out", None)


class TestStoredResultShape:
    def test_a_successful_result_says_so(self):
        assert StoredResult(handle="r1", tool="t").succeeded is True

    def test_a_refused_one_does_not(self):
        assert StoredResult(handle="r1", tool="t", exit_code=1).succeeded is False
