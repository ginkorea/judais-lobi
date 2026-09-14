# tests/test_eval_suggest.py — the generator proposes, and says so

"""`python -m core.eval suggest-pack`, and the four promises it makes.

The subject-spine design §2.4 gives this subcommand one job and three
disciplines, and every section below is one of them:

* **the draft loads.**  A page of lines somebody pastes into a manifest is
  worth nothing if the manifest then refuses it at the door, so the
  rendered YAML is fed to the two real readers —
  :meth:`core.runtime.cognition.RulePack.from_mapping` and
  :meth:`core.runtime.declarations.ToolsBlock.from_mapping` — and not to a
  validator written here, which would only ever agree with the generator;
* **every line says where it came from, and how much of it there is.**  A
  schema line is the plane's own contract; an induced line is an inference
  from receipts that happened to be recorded, and the absence of a second
  value is not evidence that there is no second value.  Both are marked and
  both carry a count;
* **it is deterministic.**  Same corpus, any order, byte-identical page —
  because a draft whose text moves between runs is a diff nobody reviews;
* **it never writes into a skill.**  `proposing never makes it true` is a
  boundary, and this is where it is enforceable.

Nothing here spends a model or dials a server.  The receipts are written
through :class:`core.runtime.replay.Recorder` — the real writer, so what
this module reads is what a mission records and not a test's idea of it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.durable import RunStore
from core.eval import suggest as mod
from core.eval.run import main as eval_main
from core.eval.suggest import (CARDINALITY, DEFAULT_IDENTIFIER, HEADER,
                               IDENTIFIER, MIN_RECEIPTS, OBSERVED, SCHEMA,
                               Draft, Evidence, Receipt, Suggestion,
                               SuggestRefused, kind_of, read_receipts,
                               read_schemas, skill_directory_above, suggest)
from core.runtime.cognition import RulePack
from core.runtime.declarations import ToolsBlock
from core.runtime.grounding import harvest_fields
from core.runtime.replay import Recorder
from core.skills.library import MANIFEST_FILE
from core.tools.bus import ToolResult

yaml = pytest.importorskip("yaml")

#: The sentence the whole feature exists to print, quoted once.
DRAFT_SENTENCE = "DRAFT — nothing here is loaded; review, prune, ship in a skill."


# ── building the two sources ─────────────────────────────────────────────────

def plane() -> dict:
    """A saved ``tools/list``, in the shape a server answers it.

    Shaped after the reference deployment's: a governed envelope
    (``result_ref`` on every result), real fields under ``data``, an enum,
    an id-named key, a uuid-formatted one, and one adapter that publishes a
    bare object because most of a real plane does.
    """
    envelope = {"result_ref": {"type": "string", "format": "uuid"},
                "handling_summary": {"type": "string"}}
    return {"tools": [
        {"name": "narrative_discovery",
         "outputSchema": {"type": "object", "properties": {
             **envelope,
             "data": {"type": "object", "properties": {
                 "job_id": {"type": "string"},
                 "corpus_asset_id": {"type": "string"},
                 "state": {"type": "string",
                           "enum": ["queued", "running", "completed"]}}}}}},
        {"name": "runs_get",
         "outputSchema": {"type": "object", "properties": {
             **envelope,
             "data": {"type": "object", "properties": {
                 "run_uuid": {"type": "string", "format": "uuid"},
                 "verdict": {"type": "string", "enum": ["pass", "fail"]},
                 "source_assets": {"type": "array", "items": {
                     "type": "object", "properties": {
                         "asset_id": {"type": "string"}}}}}}}}},
        {"name": "health", "outputSchema": {"type": "object"}},
    ]}


def saved(tmp_path: Path, payload=None, name: str = "tools.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(plane() if payload is None else payload),
                    encoding="utf-8")
    return path


def receipts(root: Path, dispatches, run_id=None) -> Path:
    """Write *dispatches* through the real recorder; return the directory.

    *dispatches* is ``(tool, payload)`` pairs; the payload is rendered into
    ``stdout`` as JSON, which is where the shadow's harvest reads a receipt
    from and therefore where this module has to.
    """
    store = RunStore(root)
    run = store.create(run_id)
    recorder = Recorder(store, run.run_id)
    for tool, payload in dispatches:
        recorder.dispatch(tool, {"args": [], "kwargs": {}},
                          ToolResult(exit_code=0, stdout=json.dumps(payload),
                                     stderr="", tool_name=tool))
    return store.directory(run.run_id)


def chained(root: Path) -> Path:
    """A recorded corpus in which one asset id is genuinely shared.

    Two tools, one value (``led.a41``) under two different keys, and a
    ``state`` that repeats — so a draft made from it has one real join and
    one trap.
    """
    return receipts(root, [
        ("mcp.catalog_get_asset",
         {"data": {"asset_id": "led.a41", "state": "ready", "bytes": 91}}),
        ("mcp.catalog_get_asset",
         {"data": {"asset_id": "led.b02", "state": "ready", "bytes": 44}}),
        ("mcp.catalog_get_asset",
         {"data": {"asset_id": "led.c73", "state": "ready", "bytes": 12}}),
        ("mcp.runs_get",
         {"data": {"run_id": "r-1", "state": "ready",
                   "source_assets": [{"asset_id": "led.a41"}]}}),
        ("mcp.runs_get",
         {"data": {"run_id": "r-2", "state": "ready",
                   "source_assets": [{"asset_id": "led.b02"}]}}),
    ])


def blocks_of(text: str) -> dict:
    """The draft's two blocks, parsed back out of the rendered page."""
    loaded = yaml.safe_load(text)
    assert isinstance(loaded, dict), text
    return loaded


def _lines_starting(prefix: str, page: str) -> list:
    """Every line of *page* that begins with *prefix* once indented.

    The escaped form of a hostile fragment still CONTAINS its text — a
    newline becomes a literal ``\\n`` inside one comment — so "the string
    is absent" is the wrong assertion and would fail on a page that is
    perfectly safe.  What must never happen is that the fragment starts a
    line, because a line is what YAML parses.
    """
    return [line for line in page.splitlines()
            if line.strip().startswith(prefix)]


# ── the draft loads, which is the whole promise ──────────────────────────────

class TestTheDraftLoads:
    """A page whose lines a manifest refuses is a page that wasted the
    review it asked for."""

    def test_the_rendered_yaml_goes_through_both_real_readers(self, tmp_path):
        draft = suggest(schemas=read_schemas(saved(tmp_path)),
                        receipts=read_receipts([chained(tmp_path / "runs")]))
        assert draft, "the fixtures suggest nothing, so this proves nothing"
        loaded = blocks_of(draft.to_yaml())
        # The real doors. Either one raising IS the failure.
        RulePack.from_mapping(loaded["cognition"])
        ToolsBlock.from_mapping(loaded["tools"])

    def test_what_it_renders_is_what_it_says_it_renders(self, tmp_path):
        """`as_mapping` is what the tests validate and `to_yaml` is what a
        person pastes; one of them being a second rendering of the other is
        the defect this asserts away."""
        draft = suggest(schemas=read_schemas(saved(tmp_path)),
                        receipts=read_receipts([chained(tmp_path / "runs")]))
        assert blocks_of(draft.to_yaml()) == draft.as_mapping()

    def test_the_generator_says_so_when_its_own_draft_does_not_load(self):
        """`problems()` asks the doors, so a bug here is reported rather
        than printed as lines to paste."""
        bad = Draft(suggestions=(Suggestion(
            block=IDENTIFIER, tool="t", key="data.x", value="jo:b",
            evidence=(Evidence(SCHEMA, 1, "made up"),)),))
        problems = bad.problems()
        assert problems and "`tools:` block" in problems[0]
        assert "jo:b" in problems[0]

    def test_a_key_no_declaration_could_name_is_dropped_not_printed(self):
        """A payload may carry `2024` or `a b` as a key; a declaration may
        not name one, and the page promises it loads."""
        drafted = suggest(receipts=[
            Receipt("a", (("data.2024", "led.a41"),)),
            Receipt("b", (("data.2024", "led.a41"),)),
            Receipt("a", (("data.2024", "led.b02"),)),
            Receipt("b", (("data.2024", "led.b02"),))])
        assert not drafted.of(IDENTIFIER)
        assert not drafted.problems()

    def test_a_newline_in_a_payload_KEY_cannot_split_the_page(self):
        """The fault this guard was written for, and it came out of ordinary
        recorded data rather than anybody hand-editing anything.

        A JSON key may contain a newline. The key itself is dropped by
        `_only_declarable` — no declaration can name it — but it still
        reached the page inside the OTHER line's provenance comment, and an
        unescaped newline there ends the comment and leaves the rest of it
        parsing as YAML. Every door passed; the page did not load.
        """
        drafted = suggest(receipts=[
            Receipt("alpha", tuple(mod._leaves(
                {"data": {"x\n  evil: yes": "shared-1",
                          "job_id": "shared-1"}}))),
            Receipt("beta", tuple(mod._leaves(
                {"data": {"job_id": "shared-1"}}))),
            Receipt("alpha", tuple(mod._leaves(
                {"data": {"x\n  evil: yes": "shared-2",
                          "job_id": "shared-2"}}))),
            Receipt("beta", tuple(mod._leaves(
                {"data": {"job_id": "shared-2"}}))),
        ])
        assert drafted.of(IDENTIFIER), "nothing drafted, so nothing proved"
        assert drafted.problems() == ()
        assert blocks_of(drafted.to_yaml()) == drafted.as_mapping()
        assert not _lines_starting("evil:", drafted.to_yaml()), (
            "the key broke out of its comment and became a YAML line")

    def test_a_newline_in_a_TOOL_name_cannot_split_the_page_either(self):
        """A tool name is recorded data too — `tools.jsonl` carries whatever
        the bus dispatched — and it is rendered into a `- name:` line and
        into every comment beneath it."""
        evil = "alpha\n  evil: yes"
        drafted = suggest(receipts=[
            Receipt(evil, (("data.job_id", "j-1"),)),
            Receipt("beta", (("data.job_id", "j-1"),)),
            Receipt(evil, (("data.job_id", "j-2"),)),
            Receipt("beta", (("data.job_id", "j-2"),)),
        ])
        assert drafted.of(IDENTIFIER), "nothing drafted, so nothing proved"
        assert drafted.problems() == ()
        assert blocks_of(drafted.to_yaml()) == drafted.as_mapping()
        assert not _lines_starting("evil:", drafted.to_yaml())

    def test_the_page_check_catches_a_comment_that_broke_its_own_line(self):
        """The braces behind `_comment_safe`'s belt.

        Built through `Evidence` directly, because that is the one way a
        raw newline can still reach a comment: every fragment the two
        halves assemble goes through the escaping owner, and this asserts
        what happens if one ever does not. The page parses — into a key
        nobody drafted — so ONLY a comparison against the blocks can see
        it, which is why the check is a comparison and not a parse.
        """
        drafted = Draft(suggestions=(Suggestion(
            block=CARDINALITY, tool="", key="state", value="one",
            evidence=(Evidence(SCHEMA, 1, "x\n  evil: yes"),)),))
        problems = drafted.problems()
        assert problems, "a page carrying a key nobody drafted passed"
        assert "parses back to something other than" in problems[0]
        assert "evil" in problems[0]

    def test_the_page_check_catches_a_page_that_does_not_parse_at_all(self):
        """The other half of the same guard, and a different branch: a
        fragment that leaves the page unparseable rather than differently
        parsed. A tab cannot start a YAML token."""
        drafted = Draft(suggestions=(Suggestion(
            block=CARDINALITY, tool="", key="state", value="one",
            evidence=(Evidence(SCHEMA, 1, "x\n\tevil: yes"),)),))
        problems = drafted.problems()
        assert problems, "an unparseable page passed"
        assert "is not YAML" in problems[0]

    def test_the_page_is_checked_and_not_only_the_blocks(self):
        """The blocks are what the object holds; the page is what a person
        pastes, and only re-reading the page can see a comment that broke
        its own line."""
        drafted = Draft(suggestions=(Suggestion(
            block=CARDINALITY, tool="", key="state", value="one",
            evidence=(Evidence(SCHEMA, 1, "enum of 2"),)),))
        assert drafted.problems() == ()
        assert mod._as_blocks(
            yaml.safe_load(drafted.to_yaml())) == drafted.as_mapping()

    def test_an_empty_page_parses_back_to_the_empty_blocks(self):
        """A block whose body is only a comment parses as `None` and is
        built as `{}`. Both loaders take both, so the normalisation in
        `_as_blocks` is a fact about pyyaml and not a fault in the draft —
        and without it the check would fire on every empty page."""
        assert Draft().problems() == ()
        assert mod._as_blocks(None) == Draft().as_mapping()

    def test_a_key_spelled_on_stays_a_string(self):
        """pyyaml is a YAML 1.1 parser and `on:` is a boolean in it. Every
        scalar this page writes is quoted for exactly this."""
        drafted = Draft(suggestions=(Suggestion(
            block=CARDINALITY, tool="", key="on", value="one",
            evidence=(Evidence(SCHEMA, 1, "enum"),)),))
        loaded = blocks_of(drafted.to_yaml())
        assert loaded["cognition"]["cardinality"] == {"on": "one"}
        assert not drafted.problems()


# ── every line says where it came from ───────────────────────────────────────

class TestTheHierarchyIsOnThePage:

    def test_the_header_sentence_is_there(self, tmp_path):
        text = suggest(schemas=read_schemas(saved(tmp_path))).to_yaml()
        assert f"# {DRAFT_SENTENCE}" in text
        assert HEADER[0] == DRAFT_SENTENCE

    def test_the_header_ranks_the_two_sources_and_refuses_both(self, tmp_path):
        text = suggest(schemas=read_schemas(saved(tmp_path))).to_yaml()
        assert "Better" in text and "grounded" in text
        assert "INDUCED" in text
        assert "proposing never makes it true" in text

    def test_every_suggestion_carries_an_evidence_count(self, tmp_path):
        draft = suggest(schemas=read_schemas(saved(tmp_path)),
                        receipts=read_receipts([chained(tmp_path / "runs")]))
        assert draft.suggestions
        for item in draft.suggestions:
            assert item.evidence, f"{item.slot} has no evidence"
            assert item.count >= 1, f"{item.slot} counts nothing"

    def test_every_rendered_line_carries_its_provenance_comment(self, tmp_path):
        draft = suggest(schemas=read_schemas(saved(tmp_path)),
                        receipts=read_receipts([chained(tmp_path / "runs")]))
        body = [line for line in draft.to_yaml().splitlines()
                if line.startswith("    ")
                and not line.lstrip().startswith(("#", "- name:"))
                and not line.rstrip().endswith(":")]
        assert len(body) >= 4, body
        for line in body:
            assert "#" in line, f"no provenance on: {line}"
            comment = line.split("#", 1)[1]
            assert comment.strip().startswith((f"{SCHEMA}:", f"{OBSERVED}:")), (
                f"a line that does not say which source it came from: {line}")

    def test_an_induced_line_says_it_is_induced_and_names_the_sample(self):
        drafted = suggest(receipts=[Receipt("t", (("data.n", 1),)),
                                    Receipt("t", (("data.n", 2),))])
        line, = drafted.of(CARDINALITY)
        assert line.sources == (OBSERVED,)
        assert "induced" in line.comment()
        assert "2 receipts" in line.comment()
        assert line.count == 2

    def test_a_schema_line_is_marked_schema_and_not_induced(self, tmp_path):
        drafted = suggest(schemas=read_schemas(saved(tmp_path)))
        assert drafted.suggestions
        for item in drafted.suggestions:
            assert item.sources == (SCHEMA,)
            assert "induced" not in item.comment()

    def test_where_both_sources_agree_the_schema_leads_and_both_are_kept(
            self, tmp_path):
        """Two sources agreeing is worth more than either, and a reader
        pruning the page has to be able to see that they did."""
        draft = suggest(
            schemas=read_schemas(saved(tmp_path, {"tools": [
                {"name": "a", "outputSchema": {"properties": {
                    "state": {"enum": ["x", "y"]}}}}]})),
            receipts=[Receipt("a", (("state", "x"),)),
                      Receipt("a", (("state", "y"),))])
        line, = [item for item in draft.of(CARDINALITY) if item.key == "state"]
        assert line.sources == (SCHEMA, OBSERVED)
        assert line.comment().index("schema:") < line.comment().index("observed:")


# ── induction is marked as induction ─────────────────────────────────────────

class TestAbsenceIsNotEvidence:

    def test_one_receipt_is_not_a_sample(self):
        """`MIN_RECEIPTS`. One receipt holding one value says nothing about
        the second receipt, and a line drawn from it would carry a count of
        one under a header promising the count means something."""
        assert not suggest(receipts=[Receipt("t", (("n", 1),))]).of(CARDINALITY)
        assert MIN_RECEIPTS == 2

    def test_the_floor_is_the_callers(self):
        drafted = suggest(receipts=[Receipt("t", (("n", 1),)),
                                    Receipt("t", (("n", 2),))],
                          min_receipts=3)
        assert not drafted.of(CARDINALITY)

    def test_two_values_in_one_receipt_refutes_the_candidate(self):
        """This is the half that is NOT induction: a receipt that carried
        two values for a field has shown the field is not single-valued."""
        drafted = suggest(receipts=[
            Receipt("t", (("items[].kind", "a"), ("items[].kind", "b"))),
            Receipt("t", (("items[].kind", "a"),))])
        assert not [item for item in drafted.of(CARDINALITY)
                    if item.key == "kind"]

    def test_a_repeated_status_is_never_proposed_as_an_identity(self, tmp_path):
        """`DISTINCT_SHARE`. `"ready"` under two tools' `state` is a status,
        and a draft proposing it as a join key would manufacture exactly the
        contradictions the linking design exists to avoid."""
        draft = suggest(receipts=read_receipts([chained(tmp_path / "runs")]))
        keys = {item.key for item in draft.of(IDENTIFIER)}
        assert "data.state" not in keys
        assert {"data.asset_id", "data.source_assets[].asset_id"} <= keys

    def test_the_shared_value_and_both_of_its_places_are_named(self, tmp_path):
        draft = suggest(receipts=read_receipts([chained(tmp_path / "runs")]))
        line, = [item for item in draft.of(IDENTIFIER)
                 if item.key == "data.asset_id"]
        assert "led.a41" in line.comment()
        assert "mcp.runs_get.data.source_assets[].asset_id" in line.comment()
        assert "induced" in line.comment()

    def test_a_value_under_one_tool_only_joins_nothing(self):
        drafted = suggest(receipts=[
            Receipt("t", (("data.job_id", "j1"),)),
            Receipt("t", (("data.other_id", "j1"),)),
            Receipt("t", (("data.job_id", "j2"),)),
            Receipt("t", (("data.other_id", "j2"),))])
        assert not drafted.of(IDENTIFIER), (
            "one tool's two keys holding one value is a payload's shape, "
            "not a cross-receipt join")


# ── what a plane's own contract supports ─────────────────────────────────────

class TestTheSchemaHalf:

    def test_an_enum_is_a_cardinality_candidate_named_by_its_field(self,
                                                                   tmp_path):
        draft = suggest(schemas=read_schemas(saved(tmp_path)))
        names = {item.key: item for item in draft.of(CARDINALITY)}
        assert set(names) == {"state", "verdict"}
        assert names["state"].value == "one"
        assert "enum" in names["state"].comment()
        assert "narrative_discovery (3)" in names["state"].comment()

    def test_a_one_value_enum_says_nothing_about_multiplicity(self, tmp_path):
        draft = suggest(schemas=read_schemas(saved(tmp_path, {"tools": [
            {"name": "a", "outputSchema": {"properties": {
                "mode": {"enum": ["only"]}}}}]})))
        assert not draft.of(CARDINALITY)

    def test_an_id_named_key_is_an_identifier_with_a_guessed_kind(self,
                                                                  tmp_path):
        draft = suggest(schemas=read_schemas(saved(tmp_path)))
        found = {(item.tool, item.key): item.value
                 for item in draft.of(IDENTIFIER)}
        assert found[("narrative_discovery", "data.job_id")] == "job"
        assert found[("narrative_discovery", "data.corpus_asset_id")] == "asset"
        assert found[("runs_get", "data.source_assets[].asset_id")] == "asset"

    def test_a_uuid_formatted_key_is_one_even_without_the_name(self, tmp_path):
        draft = suggest(schemas=read_schemas(saved(tmp_path)))
        line, = [item for item in draft.of(IDENTIFIER)
                 if item.key == "data.run_uuid"]
        assert line.value == "uuid"
        assert "format: uuid" in line.comment()

    def test_a_key_every_tool_carries_goes_to_defaults_once(self, tmp_path):
        """That is what `defaults:` is for, and it is the envelope case the
        design names by name."""
        draft = suggest(schemas=read_schemas(saved(tmp_path)))
        line, = draft.of(DEFAULT_IDENTIFIER)
        assert (line.key, line.value) == ("result_ref", "result")
        assert "all 2 tools that publish one" in line.comment(), (
            "a bare-object adapter must not VETO the plane's envelope — "
            "most of a real deployment's tools are bare-object")
        assert not [item for item in draft.of(IDENTIFIER)
                    if item.key == "result_ref"]

    def test_an_envelope_key_that_is_not_handle_shaped_is_left_alone(self,
                                                                     tmp_path):
        """`handling_summary` is on every result of a real deployment and
        joins nothing."""
        draft = suggest(schemas=read_schemas(saved(tmp_path)))
        assert "handling_summary" not in {item.key for item in draft.suggestions}

    def test_a_bare_object_contributes_nothing_and_refuses_nothing(self,
                                                                   tmp_path):
        draft = suggest(schemas=read_schemas(saved(tmp_path)))
        assert "health" not in {item.tool for item in draft.suggestions}
        assert (draft.tools_read, draft.schemas_read) == (3, 2)

    def test_one_tool_is_not_a_plane_so_nothing_is_an_envelope(self, tmp_path):
        draft = suggest(schemas=read_schemas(saved(tmp_path, {"tools": [
            {"name": "a", "outputSchema": {"properties": {
                "result_ref": {"type": "string", "format": "uuid"}}}}]})))
        assert not draft.of(DEFAULT_IDENTIFIER)
        assert [item.key for item in draft.of(IDENTIFIER)] == ["result_ref"]


class TestTheKindIsAGuessAndSaysSo:

    @pytest.mark.parametrize("path,kind", [
        ("job_id", "job"),
        ("data.corpus_asset_id", "asset"),
        ("result_ref", "result"),
        ("source_assets[]", "asset"),
        ("data.items[].run_id", "run"),
        ("run_uuid", "uuid"),
    ])
    def test_the_designs_own_worked_examples(self, path, kind):
        assert kind_of(path) == kind


# ── deterministic, or it is not reviewable ───────────────────────────────────

class TestItIsTheSameDraftTwice:

    def test_the_same_corpus_in_the_other_order_is_the_same_bytes(self,
                                                                  tmp_path):
        one = chained(tmp_path / "a")
        two = receipts(tmp_path / "b", [
            ("mcp.runs_get", {"data": {"run_id": "r-9", "state": "ready"}})])
        schemas = read_schemas(saved(tmp_path))
        first = suggest(schemas=schemas,
                        receipts=read_receipts([one, two])).to_yaml()
        second = suggest(schemas=schemas,
                         receipts=read_receipts([two, one])).to_yaml()
        assert first == second

    def test_the_schemas_in_the_other_order_are_the_same_bytes(self, tmp_path):
        forward = plane()
        backward = {"tools": list(reversed(forward["tools"]))}
        first = suggest(schemas=read_schemas(saved(tmp_path, forward))).to_yaml()
        second = suggest(
            schemas=read_schemas(saved(tmp_path, backward, "b.json"))).to_yaml()
        assert first == second

    def test_the_page_is_in_one_declared_order(self, tmp_path):
        """The sort in `suggest` is the ONE owner of what order this page is
        in — the readers it draws from are free to answer in theirs, and a
        page whose lines moved because a schema listed its keys differently
        is a diff nobody can review."""
        draft = suggest(schemas=read_schemas(saved(tmp_path)),
                        receipts=read_receipts([chained(tmp_path / "runs")]))
        slots = [item.slot for item in draft.suggestions]
        assert slots == sorted(slots)

    def test_a_schema_listing_its_keys_backwards_is_the_same_bytes(self,
                                                                   tmp_path):
        forward = {"tools": [{"name": "a", "outputSchema": {"properties": {
            "job_id": {"type": "string"}, "asset_id": {"type": "string"},
            "state": {"enum": ["x", "y"]}}}}]}
        backward = {"tools": [{"name": "a", "outputSchema": {"properties": {
            "state": {"enum": ["x", "y"]}, "asset_id": {"type": "string"},
            "job_id": {"type": "string"}}}}]}
        assert (suggest(schemas=read_schemas(saved(tmp_path, forward))).to_yaml()
                == suggest(schemas=read_schemas(
                    saved(tmp_path, backward, "b.json"))).to_yaml())

    def test_reading_it_twice_is_the_same_bytes(self, tmp_path):
        path = saved(tmp_path)
        runs = chained(tmp_path / "runs")
        pages = {suggest(schemas=read_schemas(path),
                         receipts=read_receipts([runs])).to_yaml()
                 for _ in range(3)}
        assert len(pages) == 1


# ── it never writes into a skill ─────────────────────────────────────────────

class TestItNeverWritesIntoASkill:

    def test_a_directory_holding_a_manifest_is_found(self, tmp_path):
        (tmp_path / MANIFEST_FILE).write_text("---\nname: s\n---\n",
                                              encoding="utf-8")
        assert skill_directory_above(tmp_path / "draft.yml") == tmp_path

    def test_a_pack_subdirectory_is_inside_it_too(self, tmp_path):
        (tmp_path / MANIFEST_FILE).write_text("---\nname: s\n---\n",
                                              encoding="utf-8")
        deep = tmp_path / "fixtures" / "cases"
        deep.mkdir(parents=True)
        assert skill_directory_above(deep / "draft.yml") == tmp_path

    def test_an_ordinary_directory_is_not_one(self, tmp_path):
        assert skill_directory_above(tmp_path / "draft.yml") is None

    def test_the_subcommand_refuses_the_path_and_writes_nothing(
            self, tmp_path, capsys):
        skill = tmp_path / "recon"
        skill.mkdir()
        (skill / MANIFEST_FILE).write_text("---\nname: recon\n---\n",
                                           encoding="utf-8")
        out = skill / "draft.yml"
        code = eval_main(["suggest-pack", "--schemas", str(saved(tmp_path)),
                          "--out", str(out)])
        assert code == 2
        assert not out.exists()
        message = capsys.readouterr().err
        assert MANIFEST_FILE in message and str(skill) in message

    def test_it_is_refused_before_anything_is_read(self, tmp_path, capsys):
        """A refusal that arrives after the work is a refusal that cost what
        it was meant to save — and a missing `--schemas` must not be the
        message a person gets when the real fault is where they aimed it."""
        skill = tmp_path / "recon"
        skill.mkdir()
        (skill / MANIFEST_FILE).write_text("---\nname: recon\n---\n",
                                           encoding="utf-8")
        code = eval_main(["suggest-pack", "--schemas", str(tmp_path / "nope"),
                          "--out", str(skill / "draft.yml")])
        assert code == 2
        assert MANIFEST_FILE in capsys.readouterr().err

    def test_an_ordinary_out_path_is_written(self, tmp_path, capsys):
        out = tmp_path / "drafts" / "pack.yml"
        code = eval_main(["suggest-pack", "--schemas", str(saved(tmp_path)),
                          "--out", str(out)])
        capsys.readouterr()
        assert code == 0
        assert DRAFT_SENTENCE in out.read_text(encoding="utf-8")


# ── reading the two sources ──────────────────────────────────────────────────

class TestReadingTheSources:

    def test_three_shapes_of_a_saved_tools_list_read_the_same(self, tmp_path):
        response = saved(tmp_path)
        listing = saved(tmp_path, plane()["tools"], "list.json")
        mapping = saved(tmp_path, {name: schema for name, schema
                                   in read_schemas(response).items()},
                        "map.json")
        assert read_schemas(response) == read_schemas(listing)
        assert read_schemas(response) == read_schemas(mapping)

    def test_a_plane_with_a_tool_named_tools_is_not_swallowed_by_it(self,
                                                                    tmp_path):
        """The response envelope is unwrapped only when it holds a LIST —
        otherwise one unluckily-named tool replaces the whole plane."""
        path = saved(tmp_path, {"tools": {"properties": {
            "job_id": {"type": "string"}}}, "runs_get": {"properties": {}}})
        assert set(read_schemas(path)) == {"tools", "runs_get"}

    def test_this_frameworks_own_spelling_of_the_key_is_read_too(self,
                                                                 tmp_path):
        path = saved(tmp_path, [{"name": "a", "output_schema": {
            "properties": {"job_id": {"type": "string"}}}}])
        assert "job_id" in read_schemas(path)["a"]["properties"]

    def test_a_file_that_is_not_a_tools_list_is_refused_by_name(self, tmp_path):
        path = tmp_path / "n.json"
        path.write_text("42", encoding="utf-8")
        with pytest.raises(SuggestRefused, match="not a tools/list"):
            read_schemas(path)

    def test_a_file_that_is_not_json_is_refused_by_name(self, tmp_path):
        path = tmp_path / "n.json"
        path.write_text("{", encoding="utf-8")
        with pytest.raises(SuggestRefused, match="not JSON"):
            read_schemas(path)

    def test_a_missing_file_is_refused_by_name(self, tmp_path):
        with pytest.raises(SuggestRefused, match="--schemas"):
            read_schemas(tmp_path / "gone.json")

    def test_the_catalogue_line_is_not_a_receipt(self, tmp_path):
        """`tools.jsonl` line one is the plane a run was offered, and
        reading it as a call would put input schemas into the induced
        half."""
        directory = receipts(tmp_path / "runs",
                             [("t", {"data": {"n": 1}})])
        log = directory / "tools.jsonl"
        log.write_text('{"call":0,"catalogue":[{"name":"t","input_schema":'
                       '{"properties":{"job_id":{"type":"string"}}}}]}\n'
                       + log.read_text(encoding="utf-8"), encoding="utf-8")
        found = read_receipts([tmp_path / "runs"])
        assert [receipt.tool for receipt in found] == ["t"]

    def test_a_root_that_is_not_there_contributes_nothing(self, tmp_path):
        assert read_receipts([tmp_path / "gone"]) == []

    def test_a_receipt_holding_no_json_is_read_as_nothing(self, tmp_path):
        store = RunStore(tmp_path / "runs")
        run = store.create()
        Recorder(store, run.run_id).dispatch(
            "t", {}, ToolResult(exit_code=0, stdout="a sentence", stderr="",
                                tool_name="t"))
        found = read_receipts([tmp_path / "runs"])
        assert [receipt.leaves for receipt in found] == [()]


class TestTheWalkAgreesWithTheHarvester:
    """The bare name this module prints into a `cardinality:` line has to be
    the name `harvest_fields` reports, or the line binds nothing.  Asserted
    rather than assumed, because the two walks live in two modules."""

    PAYLOAD = {"data": {"job_id": "j-1", "totals": {"records": 12481},
                        "items": [{"kind": "a", "n": 2}, {"kind": "b"}]}}

    def test_every_field_the_harvester_names_this_module_names_too(self):
        keys: set = set()
        values: dict = {}
        harvest_fields(self.PAYLOAD, keys, values)
        mine = {mod._field_of(path) for path, _ in mod._leaves(self.PAYLOAD)}
        assert set(values) <= mine, set(values) - mine
        assert mine <= keys, mine - keys

    def test_a_list_element_is_spelled_the_way_a_declaration_is(self):
        paths = {path for path, _ in mod._leaves(self.PAYLOAD)}
        assert "data.items[].kind" in paths
        assert "data.totals.records" in paths


# ── the subcommand ───────────────────────────────────────────────────────────

class TestTheSubcommand:

    def test_it_is_registered_and_needs_no_model(self):
        from core.eval.run import _parser
        actions = [action for action in _parser()._actions
                   if hasattr(action, "choices")
                   and isinstance(action.choices, dict)]
        parser = actions[0].choices["suggest-pack"]
        flags = {option for action in parser._actions
                 for option in action.option_strings}
        assert {"--schemas", "--runs", "--out", "--min-receipts"} <= flags
        assert not {"--provider", "--model", "--suite"} & flags

    def test_with_no_source_it_says_what_to_pass(self, capsys):
        assert eval_main(["suggest-pack"]) == 2
        assert "--schemas" in capsys.readouterr().err

    def test_end_to_end_it_prints_a_page_that_loads(self, tmp_path, capsys):
        code = eval_main(["suggest-pack", "--schemas", str(saved(tmp_path)),
                          "--runs", str(chained(tmp_path / "runs"))])
        text = capsys.readouterr().out
        assert code == 0
        assert DRAFT_SENTENCE in text
        loaded = blocks_of(text)
        RulePack.from_mapping(loaded["cognition"])
        ToolsBlock.from_mapping(loaded["tools"])

    def test_json_carries_the_same_blocks_and_the_header(self, tmp_path,
                                                         capsys):
        code = eval_main(["suggest-pack", "--schemas", str(saved(tmp_path)),
                          "--json"])
        report = json.loads(capsys.readouterr().out)
        assert code == 0
        assert report["header"][0] == DRAFT_SENTENCE
        assert all(entry["count"] >= 1 for entry in report["suggestions"])
        ToolsBlock.from_mapping(report["blocks"]["tools"])

    def test_a_draft_that_fails_the_checks_is_a_refusal_and_not_a_page(
            self, tmp_path, capsys, monkeypatch):
        """The branch that exists so nobody is handed lines their manifest
        will reject.

        Reached through a stubbed generator, and that is the honest way to
        reach it: with the escaping owner and the page check both in place,
        no INPUT can produce a failing draft any more — which is the point,
        and which is also why the branch needs a test that does not depend
        on one existing.
        """
        bad = Draft(suggestions=(Suggestion(
            block=IDENTIFIER, tool="t", key="data.x", value="jo:b",
            evidence=(Evidence(SCHEMA, 1, "made up"),)),), tools_read=1)
        monkeypatch.setattr(mod, "suggest", lambda **kwargs: bad)
        code = eval_main(["suggest-pack", "--schemas", str(saved(tmp_path))])
        captured = capsys.readouterr()
        assert code == 1
        assert "does not load" in captured.err and "jo:b" in captured.err
        assert DRAFT_SENTENCE not in captured.out, (
            "a draft the checks refused was printed anyway")

    def test_the_page_check_says_when_it_stood_down(self, tmp_path, capsys,
                                                    monkeypatch):
        """pyyaml is an optional extra. Without it the page cannot be read
        back, and "no problems" and "no problems I could look for" must not
        read the same on a console."""
        monkeypatch.setattr(mod, "_yaml", lambda: None)
        code = eval_main(["suggest-pack", "--schemas", str(saved(tmp_path))])
        captured = capsys.readouterr()
        assert code == 0
        assert "pyyaml" in captured.err and "could not be read back" in captured.err
        assert DRAFT_SENTENCE in captured.out

    def test_sources_that_hold_nothing_are_said_so_and_exit_two(self,
                                                                tmp_path,
                                                                capsys):
        path = saved(tmp_path, {"tools": []})
        assert eval_main(["suggest-pack", "--schemas", str(path)]) == 2
        assert "there was none" in capsys.readouterr().err

    def test_sources_that_suggest_nothing_are_still_a_page(self, tmp_path,
                                                           capsys):
        path = saved(tmp_path, {"tools": [{"name": "health",
                                           "outputSchema": {"type": "object"}}]})
        code = eval_main(["suggest-pack", "--schemas", str(path)])
        captured = capsys.readouterr()
        assert code == 0
        assert DRAFT_SENTENCE in captured.out
        assert "suggested nothing" in captured.err
