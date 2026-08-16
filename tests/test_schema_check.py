# tests/test_schema_check.py — the arguments, against the schema the tool published

"""Both engines, and the same sentence out of either.

``jsonschema`` is in the ``mission`` extra and is what runs when it is
there; the floor underneath it runs when it is not, and a deployment that
installed the extra must not get a differently-worded refusal for the same
mistake.  So every rule below is asserted **twice**, once per engine, from
one list of cases — a second list would drift the day somebody added a rule
to one of them.

The other half of this file is the honest half: what a schema check cannot
catch.  A well-typed argument meant for a different tool passes here and
always will, and the tests say so by name so that nobody reads the presence
of this module as coverage of the failure it does not cover.
"""

from __future__ import annotations

import pytest

from core.runtime import schema_check
from core.runtime.schema_check import BUILTIN, JSONSCHEMA, check, engine

SEARCH = {
    "type": "object",
    "properties": {
        "q": {"type": "string"},
        "type": {"type": "string", "enum": ["dataset", "model", "service"]},
        "limit": {"type": "integer"},
        "owner": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "facets": {"type": "array"},
        "deep": {"type": "boolean"},
    },
    "required": ["q"],
}


@pytest.fixture(params=[JSONSCHEMA, BUILTIN])
def either(request, monkeypatch):
    """Run the whole body once per engine.

    The floor is forced by taking the library away, which is exactly what
    an install without the extra looks like from inside this module — and
    it is done with ``monkeypatch`` so the next test gets it back.
    """
    if request.param == JSONSCHEMA:
        pytest.importorskip("jsonschema",
                            reason="the real validator is an optional extra")
    else:
        monkeypatch.setattr(schema_check, "_jsonschema", None)
    assert engine() == request.param
    return request.param


class TestWhatItCatches:
    def test_a_missing_required_argument(self, either):
        problem = check("catalog.search", SEARCH, {"limit": 3})
        assert "'q'" in problem
        assert "required" in problem

    def test_a_string_where_an_integer_was_declared(self, either):
        problem = check("catalog.search", SEARCH, {"q": "x", "limit": "3"})
        assert "'limit'" in problem
        assert "integer" in problem
        assert "'3'" in problem

    def test_a_value_outside_an_enum(self, either):
        problem = check("catalog.search", SEARCH, {"q": "x", "type": "corpus"})
        assert "'type'" in problem
        assert "dataset|model|service" in problem

    def test_a_boolean_is_not_an_integer(self, either):
        """It is one in Python, and a schema that said `integer` did not
        mean `True`."""
        problem = check("catalog.search", SEARCH, {"q": "x", "limit": True})
        assert "'limit'" in problem

    def test_the_refusal_names_the_tool_and_says_nothing_ran(self, either):
        problem = check("catalog.search", SEARCH, {})
        assert problem.startswith("catalog.search was NOT called")
        assert "Nothing ran" in problem

    def test_it_ends_with_the_tools_own_argument_summary(self, either):
        """A rule stated in the refusal at the turn it binds is the one a
        20B model learns; the same rule 2,000 tokens upstream is not."""
        problem = check("catalog.search", SEARCH, {})
        assert "q (string, required)" in problem
        assert "type (string: dataset|model|service)" in problem


class TestWhatItLetsThrough:
    def test_arguments_that_match(self, either):
        assert check("catalog.search", SEARCH,
                     {"q": "cables", "limit": 3, "type": "dataset"}) == ""

    def test_an_optional_argument_left_out(self, either):
        assert check("catalog.search", SEARCH, {"q": "x"}) == ""

    def test_an_anyof_optional_given_either_branch(self, either):
        assert check("catalog.search", SEARCH, {"q": "x", "owner": None}) == ""
        assert check("catalog.search", SEARCH, {"q": "x", "owner": "dana"}) == ""

    def test_a_tool_that_published_no_schema_at_all(self, either):
        """Not a hole: a tool that never said what it takes is a tool this
        harness has no authority to refuse a call to."""
        assert check("catalog.search", None, {"anything": 1}) == ""
        assert check("catalog.search", {}, {"anything": 1}) == ""

    def test_an_argument_the_schema_never_mentioned(self, either):
        """`additionalProperties` is the schema's to say, and this one did
        not say it."""
        assert check("catalog.search", SEARCH, {"q": "x", "extra": 1}) == ""

    def test_an_integer_where_a_number_was_declared(self, either):
        assert check("t", {"type": "object",
                           "properties": {"score": {"type": "number"}}},
                     {"score": 3}) == ""


class TestWhatItCannotCatchAndNeverWill:
    """The measured failure this module does **not** fix.

    On the reference deployment a four-turn mission spent two of them
    because `uv pip install …` was handed to the tool that runs **Python**,
    and then again as a subprocess install. Every one of those arguments is
    a string where a string was declared. No schema said otherwise, so no
    schema check refuses it — what refuses it is a better tool description,
    a narrower tool set or a grounding rule, and a validator that pretended
    otherwise would be worse than none.
    """

    PYTHON = {"type": "object", "properties": {"code": {"type": "string"}},
              "required": ["code"]}

    def test_a_shell_command_typed_into_the_python_tool_passes(self, either):
        assert check("run_python_code", self.PYTHON,
                     {"code": "uv pip install pandas"}) == ""

    def test_a_plausible_identifier_that_does_not_exist_passes(self, either):
        assert check("catalog.search", SEARCH, {"q": "asset.0000"}) == ""

    def test_a_rule_the_schema_did_not_state_passes(self, either):
        """Cross-field rules, formats, a path that must be inside the
        workspace: none of them are in the schema, so none of them are
        here."""
        assert check("catalog.search", SEARCH,
                     {"q": "x", "limit": -5}) == ""


class TestTheFloorIsLenientWhereItIsIgnorant:
    """Unknown is unchecked, never refused.

    A harness that refused a call because its own miniature validator did
    not understand a keyword would be inventing a refusal the tool never
    asked for, and a mission that cannot call a tool it is allowed to call
    is a worse failure than an argument the server would have rejected.
    """

    @pytest.fixture(autouse=True)
    def without_the_library(self, monkeypatch):
        monkeypatch.setattr(schema_check, "_jsonschema", None)

    def test_a_nested_violation_is_not_seen(self):
        """Stated as a limit rather than left to be discovered: this is the
        difference the extra buys."""
        nested = {"type": "object", "properties": {
            "filter": {"type": "object", "properties": {
                "limit": {"type": "integer"}}}}}
        assert check("t", nested, {"filter": {"limit": "three"}}) == ""

    def test_a_type_word_it_has_never_heard_of_is_allowed(self):
        assert check("t", {"type": "object", "properties": {
            "when": {"type": "timestamp"}}}, {"when": 7}) == ""

    def test_a_ref_it_cannot_resolve_is_allowed(self):
        assert check("t", {"type": "object", "properties": {
            "body": {"$ref": "#/$defs/thing"}}}, {"body": 1}) == ""


class TestTheRealValidatorSeesFurther:
    def test_a_nested_violation_is_caught_when_the_extra_is_installed(self):
        pytest.importorskip("jsonschema")
        nested = {"type": "object", "properties": {
            "filter": {"type": "object", "properties": {
                "limit": {"type": "integer"}}}}}
        problem = check("t", nested, {"filter": {"limit": "three"}})
        assert "filter.limit" in problem

    def test_a_schema_that_will_not_compile_is_not_a_violation(self):
        """A tool that published something odd is not a call to refuse."""
        pytest.importorskip("jsonschema")
        assert check("t", {"type": "object",
                           "properties": {"q": {"type": 7}}}, {"q": "x"}) == ""


class TestTheCallerHoldingTheWrongShape:
    def test_arguments_that_are_not_an_object_at_all(self, either):
        problem = check("t", SEARCH, ["q", "x"])
        assert "JSON object" in problem
        assert "list" in problem
