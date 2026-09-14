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
                                       ToolsBlock, values_at)

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
        assert "declares one tool twice" in str(exc.value)
        assert "'job_status'" in str(exc.value)

    def test_two_spellings_of_one_tool_are_twice_and_both_are_named(self):
        """THE SECOND ONE THE REVIEW PAID FOR. Keyed on the name as typed,
        this door passes — and then every lookup, which matches on
        `same_tool`, finds TWO entries and binds neither. The tool loses
        every declaration it had and the plane collects false notes blaming
        it for offering nothing. The refusal names both spellings, because
        an author has to know which two lines to look at."""
        with pytest.raises(DeclarationError) as exc:
            ToolsBlock.from_mapping({"entries": [
                {"name": "runs_get",
                 "identifiers": {"run_id": {"kind": "run"}}},
                {"name": "runs.get",
                 "identifiers": {"run_id": {"kind": "job"}}}]})
        message = str(exc.value)
        assert "'runs_get'" in message and "'runs.get'" in message
        assert "same_tool" in message

    def test_a_local_tool_and_a_bridged_one_are_two_entries(self):
        """The pair the rule deliberately allows: `run_shell_command` on
        this host and `mcp.run_shell_command` on a server are two tools —
        the code-plane gate already tells them apart — and a manifest may
        declare both. `entry_for`'s exact-name-first rule is what keeps
        that unambiguous."""
        block = ToolsBlock.from_mapping({"entries": [
            {"name": "runs_get", "identifiers": {"run_id": {"kind": "run"}}},
            {"name": "mcp.runs_get",
             "identifiers": {"run_id": {"kind": "job"}}}]})
        assert len(block.entries) == 2
        assert dict(block.entry_for("mcp.runs_get").identifiers) == {
            "run_id": "job"}
        assert dict(block.entry_for("runs_get").identifiers) == {
            "run_id": "run"}

    def test_every_entry_is_findable_by_the_name_it_was_written_under(self):
        """The invariant the refusal above exists for, stated as the thing
        a caller can rely on — and named for what it proves, which is
        narrower than "binds": an entry is findable **by its own
        spelling**.  A run offering a *third* spelling that two entries
        both match is the ambiguity below, and it binds neither."""
        block = ToolsBlock.from_mapping(BLOCK)
        for entry in block.entries:
            assert block.entry_for(entry.name) is entry

    def test_a_name_two_entries_match_binds_neither_and_says_so(self):
        """The one outcome where declarations vanish although every line
        of the file was accepted at the door: two entries whose
        `tool_key`s differ both match a third spelling, and an ambiguous
        match binds none of them.  Refusing is right; being quiet about it
        is not."""
        notes = []
        block = ToolsBlock.from_mapping({"entries": [
            {"name": "alpha.runs_get",
             "identifiers": {"run_id": {"kind": "run"}}},
            {"name": "zeta.runs_get",
             "identifiers": {"run_id": {"kind": "job"}}}]})
        assert block.entry_for("runs_get", notes) is None
        assert len(notes) == 1
        assert notes[0].tool == "runs_get"
        assert "'alpha.runs_get'" in notes[0].detail
        assert "'zeta.runs_get'" in notes[0].detail

    def test_and_the_note_reaches_the_resolution(self):
        """`build` passes its own list, so the silence becomes a console
        line and a record rather than a tool that declares nothing."""
        plane = PlaneDeclarations.build(
            wire={"runs_get": BARE},
            manifest={"entries": [
                {"name": "alpha.runs_get",
                 "identifiers": {"run_id": {"kind": "run"}}},
                {"name": "zeta.runs_get",
                 "identifiers": {"run_id": {"kind": "job"}}}]})
        assert [note.tool for note in plane.discrepancies
                if note.key == "name"] == ["runs_get"]

    def test_an_unambiguous_lookup_notes_nothing(self):
        notes = []
        block = ToolsBlock.from_mapping(BLOCK)
        assert block.entry_for("mcp.runs_get", notes) is not None
        assert notes == []

    def test_a_product_keyed_on_an_identifier_nobody_declared_is_refused(self):
        """A handle nothing names is a hint that can never fire, and the
        author would find out by never seeing the hint they wrote."""
        with pytest.raises(DeclarationError) as exc:
            ToolsBlock.from_mapping({"entries": [
                {"name": "start", "identifiers": {"job_id": {"kind": "job"}},
                 "produces": [{"kind": "asset", "field": "a",
                               "via": "job_status", "on": "jobid"}]}]})
        assert "'jobid'" in str(exc.value)

    def test_a_product_on_an_entry_with_no_identifiers_is_refused(self):
        """The emptiest form of the same mistake, and the one an empty
        default would have excused: a two-phase declaration whose handle
        nothing at all declares. The wire's case stands down (a server
        emits whichever verbs it chose); the manifest's never does."""
        with pytest.raises(DeclarationError) as exc:
            ToolsBlock.from_mapping({"entries": [
                {"name": "start",
                 "produces": [{"kind": "asset", "field": "a",
                               "via": "fetch", "on": "job_id"}]}]})
        assert "'job_id'" in str(exc.value)
        assert "neither it nor the plane declares one" in str(exc.value)

    def test_a_product_may_be_keyed_on_a_plane_default(self):
        """`defaults` are identifiers of every tool of the plane, so the
        envelope's own handle is a legal thing to key a chain on."""
        block = ToolsBlock.from_mapping({
            "defaults": {"identifiers": {"result_ref": {"kind": "result"}}},
            "entries": [{"name": "start",
                         "produces": [{"kind": "asset", "field": "a",
                                       "via": "fetch", "on": "result_ref"}]}]})
        assert block.entries[0].produces[0].on == "result_ref"

    def test_the_wire_may_declare_a_product_without_declaring_a_handle(self):
        """The stand-down, and it is `None` rather than emptiness: a server
        emits whichever verbs its generator knows, and refusing an
        `x-produces` because the same schema published no `x-identifiers`
        would be this reader inventing a rule for somebody else's tooling."""
        plane = PlaneDeclarations.build(wire={"t": {
            "type": "object", "properties": {"job_id": {}},
            "x-produces": [{"kind": "asset", "field": "a", "via": "fetch",
                            "on": "job_id"}]}})
        assert plane.for_tool("t").produces[0].via == "fetch"
        assert plane.discrepancies == ()

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

    def test_a_boolean_key_is_named_by_the_word_that_was_typed(self):
        """pyyaml hands back `True` for `on`, `yes` and `true` alike, so a
        refusal quoting `True` sends an author looking for a word their
        file does not contain. Outside a `produces` entry — where `on` is
        the only key it could be — a boolean key is named by its family."""
        with pytest.raises(DeclarationError) as exc:
            ToolsBlock.from_mapping({"entries": [
                {"name": "t", "identifiers": {True: {"kind": "job"}}}]})
        message = str(exc.value)
        assert "`on`, `yes` or `true`" in message
        assert "True" not in message

    def test_a_false_key_is_named_by_its_own_family(self):
        with pytest.raises(DeclarationError) as exc:
            ToolsBlock.from_mapping({"entries": [
                {"name": "t", "identifiers": {"job_id": {"kind": "job"}},
                 "produces": [{"kind": "asset", "field": "a", "via": "f",
                               True: "job_id", False: "extra"}]}]})
        assert "`off`, `no` or `false`" in str(exc.value)

    def test_a_manifest_fallback_that_narrows_nothing_states_no_shape(self):
        """*Does this schema say anything* has one owner on both sides of
        the door: a manifest's `{}` or `{type: object}` narrows nothing,
        exactly as a server's bare object does, so it states no shape
        rather than claiming one."""
        block = ToolsBlock.from_mapping({"entries": [
            {"name": "t", "output_schema": {"type": "object"}}]})
        assert block.entries[0].shape is None

    def test_a_read_block_cannot_be_edited_afterwards(self):
        """A declaration that could be edited after the door is a
        declaration the door did not validate — and a JSON schema is nested
        all the way down, so a frozen top level over a live `properties`
        would be the reassuring half of immutability."""
        block = ToolsBlock.from_mapping({"entries": [
            {"name": "t", "output_schema": {
                "type": "object", "properties": {"job_id": {"type": "string"}}}}
        ]})
        shape = block.entries[0].shape
        with pytest.raises(TypeError):
            shape["properties"] = {}
        with pytest.raises(TypeError):
            shape["properties"]["job_id"] = {}

    def test_the_schema_is_not_the_callers_object_any_more(self):
        """The leak this closes: a mapping handed straight off a YAML load
        is still the loader's, and a caller that edited it afterwards would
        change what a run declares."""
        raw = {"type": "object", "properties": {"job_id": {}}}
        block = ToolsBlock.from_mapping({"entries": [
            {"name": "t", "output_schema": raw}]})
        raw["properties"]["job_id"] = {"type": "number"}
        assert dict(block.entries[0].shape["properties"]["job_id"]) == {}

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

    def test_an_unusable_extension_key_takes_nothing_away_either(self):
        """THE ONE THE REVIEW PAID FOR. A verb recorded on key PRESENCE is
        handed back empty when the read failed, and precedence then lets a
        malformed `x-identifiers` ERASE the manifest's identifiers for that
        tool — silently, under a note saying the key contributed nothing.
        Contributing nothing has to mean nothing to the answer as well as
        nothing to the log."""
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": {
                "type": "object",
                "properties": {"job_id": {}, "corpus_asset_id": {}},
                "x-identifiers": ["job_id"]}},
            manifest=BLOCK)
        declaration = plane.for_tool("narrative_discovery")
        assert dict(declaration.identifiers) == {
            "result_ref": "result", "corpus_asset_id": "asset",
            "job_id": "job"}
        assert declaration.sources["identifiers"] == MANIFEST
        assert "outputSchema" in {note.key for note in plane.discrepancies}

    def test_an_explicitly_empty_wire_verb_is_a_declaration_and_wins(self):
        """The other side of the same line, and the reason it is a line:
        `x-identifiers: {}` is a value this reader UNDERSTOOD — the plane
        saying *this tool identifies nothing* — so it wins the verb, while
        an unusable one leaves the manifest's answer standing. Unusable and
        empty are different facts about a plane."""
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": {
                "type": "object", "properties": {"job_id": {}},
                "x-identifiers": {}}},
            manifest=BLOCK)
        declaration = plane.for_tool("narrative_discovery")
        assert dict(declaration.identifiers) == {}
        assert declaration.sources["identifiers"] == WIRE

    def test_one_unusable_verb_does_not_take_the_others_down(self):
        """Per verb, in the failure direction too: a server whose
        `x-produces` is nonsense has still said what its keys identify."""
        plane = PlaneDeclarations.build(wire={"t": {
            "type": "object", "properties": {"job_id": {}},
            "x-identifiers": {"job_id": {"kind": "job"}},
            "x-produces": "later"}})
        declaration = plane.for_tool("t")
        assert dict(declaration.identifiers) == {"job_id": "job"}
        assert declaration.produces == ()
        assert declaration.sources["identifiers"] == WIRE

    def test_one_bad_key_makes_the_whole_verb_unusable(self):
        """And **not** a smaller verb.  The verb readers are partial by
        construction — they return every entry they understood beside a
        fault — so half of a server's `x-identifiers` is available to be
        taken.  Taking it is the worst of the three answers: a plane that
        mistyped one key would silently NARROW what the manifest
        correctly declared, under a note that describes a key rather than
        the loss."""
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": {
                "type": "object",
                "properties": {"job_id": {}, "corpus_asset_id": {}},
                "x-identifiers": {"job_id": {"kind": "job"},
                                  "corpus_asset_id": 7}}},
            manifest=BLOCK)
        declaration = plane.for_tool("narrative_discovery")
        assert dict(declaration.identifiers) == {
            "result_ref": "result", "corpus_asset_id": "asset",
            "job_id": "job"}
        assert declaration.sources["identifiers"] == MANIFEST
        assert "outputSchema" in {note.key for note in plane.discrepancies}


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

    def test_a_tool_the_run_does_not_offer_is_noted_once(self):
        plane = PlaneDeclarations.build(wire={"runs_get": BARE},
                                        manifest=BLOCK)
        assert [(note.tool, note.key) for note in plane.discrepancies] \
            == [("narrative_discovery", "name")]

    def test_a_tool_the_run_holds_through_another_door_draws_no_note(self):
        """The servers are not the whole plane. A mission runs bridged
        tools beside this package's own, so a declaration about a built-in
        the mission actually holds is true — and blaming it on a
        `tools/list` that was never asked about `fs` would be a false note,
        on a console, at the top of every run."""
        plane = PlaneDeclarations.build(
            wire={"runs_get": BARE}, manifest=BLOCK,
            offered=["runs_get", "narrative_discovery"])
        assert plane.discrepancies == ()
        assert dict(plane.identifiers_for("narrative_discovery"))

    def test_the_offered_set_is_matched_the_same_way_as_everything_else(self):
        """`same_tool` here too: a mission offering the namespaced spelling
        holds the tool a manifest named bare."""
        plane = PlaneDeclarations.build(
            wire={"runs_get": BARE}, manifest=BLOCK,
            offered=["runs_get", "mcp.narrative_discovery"])
        assert plane.discrepancies == ()

    def test_saying_nothing_about_the_offered_set_falls_back_to_the_wire(self):
        """Empty means *nobody said*, not *nothing is offered*: a caller
        that does not pass the resolved set gets the behaviour it had
        before there was one, rather than a note against every tool."""
        plane = PlaneDeclarations.build(wire={"runs_get": BARE},
                                        manifest=BLOCK, offered=())
        assert [note.tool for note in plane.discrepancies] \
            == ["narrative_discovery"]

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

    @pytest.mark.parametrize("version", [DECLARATIONS_SCHEMA_VERSION + 1, 0,
                                         -1, None, True, "1", 1.0])
    def test_a_version_this_reader_cannot_take_is_refused(self, version):
        """Both ends of the range. A newer writer knows things this reader
        does not; `0`, a missing key and a string are not records any
        version of this writer wrote, and reading one as version 1 would
        rebuild hints out of a line nobody meant as declarations."""
        record = PlaneDeclarations.build(manifest=BLOCK).as_record()
        record[DECLARATIONS_KEY] = version
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

    def test_a_note_renders_as_one_line_naming_the_tool_and_the_key(self):
        """What the console block is made of, and the whole of what makes a
        discrepancy actionable: which tool, which key, and what to do."""
        plane = PlaneDeclarations.build(
            wire={"narrative_discovery": {
                "type": "object", "properties": {"job_id": {}},
                "x-identifiers": {"job_id": {"kind": "run"}}}},
            manifest=BLOCK)
        line = plane.discrepancies[0].sentence()
        assert line.startswith("narrative_discovery · identifiers:")
        assert "\n" not in line


class TestWhatAKeyPathPointsAt:
    """`values_at` is the walker for the grammar this module admits.

    It lives here rather than beside the harvest because the grammar does:
    a second walker would be free to read a path the door would not have
    accepted, and the whole value of a declared identifier is that it is
    exact.  The tests are mostly about what a path does NOT reach — a
    wrong link is the one mistake in this design that manufactures
    contradictions out of tools that never disagreed.
    """

    ENVELOPE = {"data": {"job_id": "jl-731",
                         "items": [{"id": "a"}, {"id": "b"}]},
                "meta": {"job_id": "jl-999"},
                "source_assets": ["led.a41", "led.b02"]}

    def test_a_dotted_path_walks_into_the_object(self):
        assert values_at(self.ENVELOPE, "data.job_id") == ("jl-731",)

    def test_and_does_not_reach_the_same_name_elsewhere(self):
        """The whole reason this is not the flat harvester: `data.job_id`
        is a declaration about one key, and a governed envelope carries
        the same word in several places."""
        assert values_at(self.ENVELOPE, "meta.job_id") == ("jl-999",)

    def test_a_bracket_segment_is_every_element_of_the_list(self):
        assert values_at(self.ENVELOPE, "source_assets[]") \
            == ("led.a41", "led.b02")

    def test_and_walks_on_from_each_of_them(self):
        assert values_at(self.ENVELOPE, "data.items[].id") == ("a", "b")

    def test_a_plain_segment_over_a_list_matches_nothing(self):
        """`source_assets.id` says the payload has an object there, and
        reading it as "the first element's" would be this walker inventing
        a declaration nobody wrote."""
        assert values_at(self.ENVELOPE, "source_assets.id") == ()

    def test_a_bracket_segment_over_a_scalar_matches_nothing(self):
        assert values_at(self.ENVELOPE, "data[].job_id") == ()

    def test_a_key_the_payload_does_not_carry_matches_nothing(self):
        assert values_at(self.ENVELOPE, "data.absent") == ()

    def test_a_path_the_grammar_would_refuse_matches_nothing(self):
        """It can only arrive here from a door that already refused it, so
        the answer is silence rather than a second refusal message."""
        assert values_at(self.ENVELOPE, "data..job_id") == ()
        assert values_at(self.ENVELOPE, "") == ()

    def test_a_payload_that_is_not_a_mapping_matches_nothing(self):
        assert values_at([{"job_id": "x"}], "job_id") == ()

    def test_the_order_is_the_payload_s_own(self):
        """Which is what makes a walk over one receipt a function of that
        receipt's bytes."""
        assert values_at({"rows": [{"id": "z"}, {"id": "a"}]},
                         "rows[].id") == ("z", "a")
