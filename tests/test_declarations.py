# tests/test_declarations.py — what a plane declares, and who wins when two doors disagree

"""The declaration layer, tested as the two doors it is.

`core/runtime/declarations.py` resolves what a tool plane says its tools
RETURN out of two sources that can contradict each other: the wire (a
server's MCP ``outputSchema``, including the ``x-`` semantic extensions)
and a skill manifest's ``tools:`` block.  Three claims run through every
test here.

**The wire wins, always.**  On shape outright — a manifest may not
re-declare a shape a server publishes — and on semantics per tool per
verb.  The argument is not taste: the wire is the plane speaking about
itself now, the manifest is a platform's memory of the plane, and when a
memory disagrees with the thing it remembers the thing is right.

**A disagreement is never silent.**  Every one is a counted
:class:`~core.runtime.declarations.Discrepancy` naming the tool and the
key, and it reaches both a person (the console) and the log (the
``reasoning.jsonl`` record), because the usual outcome of a stale
manifest is a hint that quietly binds nothing for a year.

**Nothing here refuses a mission.**  The one door that refuses is
:meth:`ToolsBlock.from_mapping`, and it refuses a FILE, at load, while
the author is looking at it — a malformed identifier costs nothing
visible and so cannot be found any later.  A server that publishes
nonsense contributes nothing and is noted; a bare-object schema, which is
what a generator emits for every return type it could not narrow,
contributes nothing and is not even noted.
"""

import pytest

from core.runtime.declarations import (DECLARATIONS_KEY,
                                       DECLARATIONS_SCHEMA_VERSION, MANIFEST,
                                       WIRE, DeclarationError,
                                       PlaneDeclarations, Produced,
                                       ToolsBlock)

#: The reference shape of a manifest block: a plane-wide handle, one tool
#: with two identifiers and a two-phase product, one tool with none.
BLOCK = {
    "defaults": {"identifiers": {"result_ref": {"kind": "result"}}},
    "entries": [
        {"name": "narrative_discovery",
         "identifiers": {"corpus_asset_id": {"kind": "asset"},
                         "job_id": {"kind": "job"}},
         "establishes": ["job_id"],
         "produces": [{"kind": "asset", "field": "label_set_asset_id",
                       "via": "job_status", "on": "job_id"}]},
        {"name": "runs_get",
         "identifiers": {"run_id": {"kind": "run"},
                         "source_assets[]": {"kind": "asset"}},
         "establishes": ["verdict", "withheld_count"]},
    ],
}

#: A server's ``outputSchema`` that says something: two keys, no semantics.
SHAPED = {"type": "object",
          "properties": {"job_id": {"type": "string"},
                         "corpus_asset_id": {"type": "string"}}}

#: The other ordinary case, and the one most adapters emit: an object the
#: generator could not narrow.  It has to contribute nothing and refuse
#: nothing, because that is the behaviour this whole layer is added on top
#: of without changing.
BARE = {"type": "object"}


def _block(**changes):
    """:data:`BLOCK` with one entry replaced, for a one-line variation."""
    entries = [dict(entry) for entry in BLOCK["entries"]]
    entries[0].update(changes)
    return {"defaults": dict(BLOCK["defaults"]), "entries": entries}


# ── the manifest door ────────────────────────────────────────────────────────

class TestTheBlockIsReadAllTheWayDownAtTheDoor:
    """A declaration that does not stand up has to be refused while an
    author is looking at the file.  Nothing downstream can find it: an
    identifier the reader cannot parse simply binds nothing, silently and
    forever, and the run looks exactly like a run with no declarations."""

    def test_the_reference_block_reads(self):
        block = ToolsBlock.from_mapping(BLOCK)
        assert dict(block.defaults) == {"result_ref": "result"}
        assert [entry.name for entry in block.entries] \
            == ["narrative_discovery", "runs_get"]
        assert dict(block.entries[0].identifiers) == {
            "corpus_asset_id": "asset", "job_id": "job"}
        assert block.entries[0].produces == (
            Produced(kind="asset", field="label_set_asset_id",
                     via="job_status", on="job_id"),)

    def test_no_block_at_all_is_an_empty_block(self):
        assert not ToolsBlock.from_mapping(None)

    def test_a_declared_empty_block_reads_as_empty_and_not_as_absent(self):
        """`{}` is a skill that wrote the key, and the difference between
        that and `None` is the one composition has to keep."""
        assert ToolsBlock.from_mapping({}) == ToolsBlock()

    @pytest.mark.parametrize("raw, fragment", [
        ({"entrys": []}, "'entrys'"),
        ({"defaults": {"establishes": ["x"]}}, "'establishes'"),
        ({"entries": {"name": "t"}}, "list"),
        ({"entries": [{"identifiers": {}}]}, "no `name`"),
        ({"entries": [{"name": "t", "identifiers": ["job_id"]}]}, "mapping"),
        ({"entries": [{"name": "t", "identifiers": {"job id": {"kind": "j"}}}]},
         "key path"),
        ({"entries": [{"name": "t", "identifiers": {"job_id": {"kind": ""}}}]},
         "states no `kind`"),
        ({"entries": [{"name": "t",
                       "identifiers": {"job_id": {"kind": "job:1"}}}]},
         "without `:` or `#`"),
        ({"entries": [{"name": "t", "establishes": "verdict"}]}, "list"),
        ({"entries": [{"name": "t", "produces": [{"kind": "asset"}]}]},
         "states no"),
        ({"entries": [{"name": "t", "output_schema": ["object"]}]},
         "JSON-schema mapping"),
    ])
    def test_a_shape_fault_is_refused_naming_what_is_wrong(self, raw,
                                                           fragment):
        with pytest.raises(DeclarationError) as exc:
            ToolsBlock.from_mapping(raw)
        assert fragment in str(exc.value)

    def test_a_kind_may_not_carry_the_subject_separator(self):
        """A subject will be spelled ``kind:value`` and a receipt
        ``tool#seq``.  A kind carrying either separator puts two namespaces
        into one string, which is the one mistake that cannot be undone
        once a link has been written down."""
        with pytest.raises(DeclarationError) as exc:
            ToolsBlock.from_mapping({"entries": [
                {"name": "t", "identifiers": {"job_id": {"kind": "a#b"}}}]})
        assert "`:` or `#`" in str(exc.value)

    def test_the_same_tool_declared_twice_in_one_manifest_is_refused(self):
        """Within one file, and refused rather than merged: which entry
        binds would otherwise be a fact about listing order, and the author
        would spend the rest of the file's life editing the other one."""
        with pytest.raises(DeclarationError) as exc:
            ToolsBlock.from_mapping({"entries": [
                {"name": "job_status", "establishes": ["state"]},
                {"name": "job_status", "establishes": ["verdict"]}]})
        assert "declares 'job_status' twice" in str(exc.value)

    def test_a_product_keyed_on_an_identifier_nobody_declared_is_refused(self):
        """A handle nothing names is a hint that can never fire, and the
        author would find out by never seeing the hint they wrote."""
        with pytest.raises(DeclarationError) as exc:
            ToolsBlock.from_mapping({"entries": [
                {"name": "start", "identifiers": {"job_id": {"kind": "job"}},
                 "produces": [{"kind": "asset", "field": "a",
                               "via": "job_status", "on": "jobid"}]}]})
        assert "'jobid'" in str(exc.value)

    def test_a_product_may_be_keyed_on_a_plane_default(self):
        """`defaults` are identifiers of every tool of the plane, so the
        envelope's own handle is a legal thing to key a chain on."""
        block = ToolsBlock.from_mapping({
            "defaults": {"identifiers": {"result_ref": {"kind": "result"}}},
            "entries": [{"name": "start",
                         "produces": [{"kind": "asset", "field": "a",
                                       "via": "fetch", "on": "result_ref"}]}]})
        assert block.entries[0].produces[0].on == "result_ref"

    def test_a_bare_on_is_the_key_it_was_typed_as(self):
        """pyyaml is a YAML 1.1 parser and `on` is a YAML 1.1 boolean, so a
        manifest writing `on: job_id` hands this reader the key `True`.
        That is not a mistake an author could act on — it is the word the
        vocabulary uses, parsed by the loader the mission itself uses — so
        it is read back rather than refused with a lecture about quoting."""
        block = ToolsBlock.from_mapping({"entries": [
            {"name": "start", "identifiers": {"job_id": {"kind": "job"}},
             "produces": [{"kind": "asset", "field": "a", "via": "fetch",
                           True: "job_id"}]}]})
        assert block.entries[0].produces[0].on == "job_id"

    def test_every_problem_arrives_in_one_message(self):
        """An author fixing a block should edit the file once.  Three
        faults, three lines, one refusal — the same idiom the manifest and
        the rule pack refuse in."""
        with pytest.raises(DeclarationError) as exc:
            ToolsBlock.from_mapping({"entries": [
                {"name": "t", "identifiers": {"job id": {"kind": "job"}},
                 "establishes": "verdict", "unknown": 1}]})
        message = str(exc.value)
        assert message.count("\n    - ") == 3, message


# ── the wire door, and precedence ────────────────────────────────────────────

class TestTheWireOwnsShape:
    def test_a_published_schema_owns_the_shape(self):
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": SHAPED}, manifest=BLOCK)
        assert plane.for_tool("narrative_discovery").shape == WIRE

    def test_a_manifest_shape_is_the_fallback_where_nothing_is_published(self):
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": BARE},
            manifest=_block(output_schema={"type": "object",
                                           "properties": {"job_id": {}}}))
        assert plane.for_tool("narrative_discovery").shape == MANIFEST

    def test_a_manifest_may_not_re_declare_a_published_shape(self):
        """The reference platform's own rule, adopted: a second copy of a
        shape is a copy that drifts.  The wire's is used and the manifest's
        is ignored — and the discrepancy names the tool and the key, so the
        stale file gets fixed instead of quietly disagreeing."""
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": SHAPED},
            manifest=_block(output_schema={"type": "object",
                                           "properties": {"gone": {}}}))
        declaration = plane.for_tool("narrative_discovery")
        assert declaration.shape == WIRE
        assert [(note.tool, note.key) for note in plane.discrepancies
                if note.key == "output_schema"] \
            == [("narrative_discovery", "output_schema")]


class TestTheWireOwnsSemanticsPerVerb:
    """`x-identifiers`, `x-establishes` and `x-produces` are the same three
    verbs the manifest speaks, arriving through the door that cannot be
    stale.  Precedence is per tool per VERB: a server that declares its
    identifiers and says nothing about what it establishes leaves the
    manifest's `establishes` standing."""

    WIRE_SCHEMA = {
        "type": "object",
        "properties": {"job_id": {"type": "string"}},
        "x-identifiers": {"job_id": {"kind": "run"}},
    }

    def test_the_wire_identifiers_replace_the_manifests(self):
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": self.WIRE_SCHEMA}, manifest=BLOCK)
        declaration = plane.for_tool("narrative_discovery")
        assert dict(declaration.identifiers) == {"job_id": "run"}
        assert declaration.sources["identifiers"] == WIRE

    def test_a_verb_the_wire_did_not_speak_stays_the_manifests(self):
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": self.WIRE_SCHEMA}, manifest=BLOCK)
        declaration = plane.for_tool("narrative_discovery")
        assert declaration.establishes == ("job_id",)
        assert declaration.sources["establishes"] == MANIFEST

    def test_the_disagreement_is_counted_and_names_the_tool_and_the_verb(self):
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": self.WIRE_SCHEMA}, manifest=BLOCK)
        notes = [note for note in plane.discrepancies
                 if note.key == "identifiers"]
        assert len(notes) == 1
        assert notes[0].tool == "narrative_discovery"
        assert "x-identifiers" in notes[0].detail

    def test_agreement_is_silent(self):
        """Two doors saying the same thing is not news, and a note about it
        would teach a reader to skip the notes."""
        agreeing = {"type": "object",
                    "properties": {"job_id": {}, "corpus_asset_id": {}},
                    "x-identifiers": {"corpus_asset_id": {"kind": "asset"},
                                      "job_id": {"kind": "job"}}}
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": agreeing, "runs_get": BARE},
            manifest=BLOCK)
        assert plane.discrepancies == ()
        assert plane.for_tool("narrative_discovery").sources["identifiers"] \
            == WIRE

    def test_a_server_alone_declares_the_whole_plane(self):
        """The recommended end state: a server generated from typed
        contracts emits the verbs and the manifest has nothing to say."""
        plane = PlaneDeclarations.build(
            wire={"mcp.narrative_discovery": self.WIRE_SCHEMA})
        assert dict(plane.identifiers_for("mcp.narrative_discovery")) \
            == {"job_id": "run"}
        assert plane.discrepancies == ()

    def test_an_unusable_extension_key_contributes_nothing_and_is_noted(self):
        """A server is not a file somebody is editing: a schema generator
        that emitted nonsense must not end a mission, and must not go
        unmentioned either."""
        plane = PlaneDeclarations.build(wire={"t": {
            "type": "object", "properties": {"job_id": {}},
            "x-identifiers": ["job_id"]}})
        assert not plane.for_tool("t")
        assert [note.key for note in plane.discrepancies] == ["outputSchema"]


class TestABareObjectContributesNothingAndRefusesNothing:
    """Eight of one real deployment's adapters declare real shapes and the
    rest fall back to a bare object.  Those tools have to degrade to
    exactly the behaviour they had before this module existed — no shape,
    no verbs, and no note, because a fallback shape is not a plane
    disagreeing with anybody."""

    @pytest.mark.parametrize("schema", [BARE, {}, None,
                                        {"type": "object",
                                         "additionalProperties": True}])
    def test_it_declares_nothing_and_says_nothing(self, schema):
        plane = PlaneDeclarations.build(wire={"t": schema})
        declaration = plane.for_tool("t")
        assert not declaration
        assert dict(declaration.identifiers) == {}
        # The shape too, and this is the half that needs saying: a plane
        # that claimed to OWN the shape of a tool whose schema narrows
        # nothing would make every manifest fallback for that tool a
        # discrepancy, which is the whole feature refusing the ordinary
        # case.
        assert declaration.shape == ""
        assert plane.discrepancies == ()

    def test_a_manifest_declaration_survives_a_bare_schema(self):
        """The fallback door's whole purpose: the platform's memory is all
        there is for a server that says nothing about its results."""
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": BARE}, manifest=BLOCK)
        assert dict(plane.identifiers_for("narrative_discovery")) == {
            "result_ref": "result", "corpus_asset_id": "asset",
            "job_id": "job"}

    def test_a_bare_schema_never_says_a_key_is_absent(self):
        """The check that a declared key is not in the published properties
        must not fire here: `{"type": "object"}` is silence, not a
        statement that `job_id` will not be there."""
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": BARE, "runs_get": BARE},
            manifest=BLOCK)
        assert plane.discrepancies == ()


class TestAnAnnotationOnAKeyThePlaneDoesNotCarry:
    def test_it_binds_nothing_and_the_note_says_so(self):
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": {
                "type": "object", "properties": {"job_id": {}}}},
            manifest=BLOCK)
        notes = [note for note in plane.discrepancies
                 if note.key.startswith("identifiers: ")]
        assert [note.key for note in notes] \
            == ["identifiers: corpus_asset_id"]
        assert "binds nothing" in notes[0].detail

    def test_a_plane_default_is_not_a_stale_key(self):
        """`defaults` are a statement about the plane.  A tool that does
        not carry the envelope's handle is an ordinary tool, and a note per
        tool per default would be noise nobody reads."""
        plane = PlaneDeclarations.build(
            wire={"runs_get": {"type": "object",
                               "properties": {"run_id": {},
                                              "source_assets": {}}},
                  "narrative_discovery": BARE},
            manifest=BLOCK)
        assert [note.key for note in plane.discrepancies] == []

    def test_a_tool_the_plane_does_not_offer_is_noted_once(self):
        plane = PlaneDeclarations.build(wire={"runs_get": BARE},
                                        manifest=BLOCK)
        assert [(note.tool, note.key) for note in plane.discrepancies] \
            == [("narrative_discovery", "name")]

    def test_with_no_server_there_is_nothing_to_be_stale_against(self):
        """A built-in plane and an offline replay: nothing spoke, so no
        memory of a plane can be out of date."""
        plane = PlaneDeclarations.build(wire=None, manifest=BLOCK)
        assert plane.discrepancies == ()
        assert len(plane) == 2


# ── how it is found again ────────────────────────────────────────────────────

class TestLookupIsThisFrameworksOneAnswerToWhichTool:
    def test_a_manifest_name_finds_the_bridged_tool(self):
        """A manifest is written the way a server advertises a tool and the
        bridge registers it namespaced.  `same_tool` is what every other
        surface matches on, so an author writes one spelling."""
        plane = PlaneDeclarations.build(
            wire={"mcp.narrative_discovery": SHAPED}, manifest=BLOCK)
        assert dict(plane.identifiers_for("mcp.narrative_discovery")) \
            == {"result_ref": "result", "corpus_asset_id": "asset",
                "job_id": "job"}

    def test_an_exact_name_wins_over_a_near_one(self):
        plane = PlaneDeclarations.build(
            wire={"mcp.runs_get": BARE, "runs_get": BARE}, manifest=BLOCK)
        assert plane.for_tool("runs_get").tool == "runs_get"

    def test_a_name_that_matches_two_declarations_matches_neither(self):
        """A coin flip about which subject kind a value identifies is the
        one mistake this layer must not make."""
        plane = PlaneDeclarations.build(
            wire={"mcp.runs_get": SHAPED, "mcp2.runs_get": SHAPED})
        assert plane.for_tool("runs_get") is None


class TestTheRecordIsWhatAReplayReadsBack:
    def test_it_states_its_own_version(self):
        record = PlaneDeclarations.build(manifest=BLOCK).as_record()
        assert record[DECLARATIONS_KEY] == DECLARATIONS_SCHEMA_VERSION

    def test_a_round_trip_carries_every_hint_and_every_disagreement(self):
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": {
                "type": "object", "properties": {"job_id": {}}}},
            manifest=BLOCK)
        again = PlaneDeclarations.from_record(plane.as_record())
        assert again.tools.keys() == plane.tools.keys()
        for name, declaration in plane.tools.items():
            other = again.tools[name]
            assert dict(other.identifiers) == dict(declaration.identifiers)
            assert other.establishes == declaration.establishes
            assert other.produces == declaration.produces
            assert dict(other.sources) == dict(declaration.sources)
            assert other.shape == declaration.shape
        assert again.discrepancies == plane.discrepancies

    def test_the_schemas_themselves_are_not_in_it(self):
        """A record exists so a replay steers under what the live run
        steered under, and that is the semantics.  Copying the plane's
        schemas into a log would be a second copy of the wire's own answer,
        inside a file somebody has to read."""
        record = PlaneDeclarations.build(wire={"narrative_discovery": SHAPED},
                                         manifest=BLOCK).as_record()
        assert record["tools"]["narrative_discovery"]["shape"] == WIRE
        assert "properties" not in str(record)

    def test_a_record_from_a_newer_writer_is_refused(self):
        record = PlaneDeclarations.build(manifest=BLOCK).as_record()
        record[DECLARATIONS_KEY] = DECLARATIONS_SCHEMA_VERSION + 1
        with pytest.raises(DeclarationError):
            PlaneDeclarations.from_record(record)


class TestNothingHereCanBeEditedAfterItIsBuilt:
    def test_the_resolved_plane_is_read_only(self):
        plane = PlaneDeclarations.build(manifest=BLOCK)
        with pytest.raises(TypeError):
            plane.tools["narrative_discovery"] = None
        with pytest.raises(TypeError):
            plane.for_tool("runs_get").identifiers["run_id"] = "job"

    def test_the_console_line_says_what_was_resolved(self):
        plane = PlaneDeclarations.build(wire={"narrative_discovery": SHAPED},
                                        manifest=BLOCK)
        assert "2 tool(s) declared" in plane.describe()
        assert "identifier(s)" in plane.describe()
