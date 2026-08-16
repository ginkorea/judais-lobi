# tests/test_skill_manifest.py — loading a SKILL.md into a closed set and a prompt

"""The manifest is content; this module tests the mechanism that reads it.

The refusals matter more than the happy path. A manifest that loaded
"successfully" with an empty closed set, or a closed set silently
narrowed to whatever the server happened to offer, produces a mission
that answers from the model's memory of the platform — and the
transcript looks like every other transcript.
"""

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from core.runtime.skills import (
    CODE_PLANE_SCOPES,
    SkillManifest,
    SkillManifestError,
    SkillToolsUnavailable,
    available_skills,
    code_plane_tools,
    load_skill,
    sandbox_name,
)
from core.tools.bus import ToolBus
from core.tools.descriptors import ALL_DESCRIPTORS
from core.tools.sandbox import BwrapSandbox, NoneSandbox

MANIFEST = textwrap.dedent("""\
    ---
    name: catalogue-recon
    description: >-
      What governed data exists, and what may be done with it.
    skill:
      skill_id: catalogue_recon
      version: 0.1.0
      when_to_use: >-
        Before any orchestration skill.
      inputs:
        mission: string
        focus: string?
      allowed_tools:
        - catalog_search_assets   # the primary instrument
        - catalog_get_asset
        - Read?
      policy:
        - Never invent an asset id.
        - Never widen a posture.
      output_format: >-
        A table, then one paragraph per asset that matters.
      evidence_requirements: >-
        Every row cites the asset id it came from.
      grounding:
        identifier_pattern: '\\b[a-z]+\\.[0-9a-f]{4,}\\b'
        ignore:
          - example.dead
        max_repairs: 1
    ---

    # Catalogue recon

    The catalogue is the only thing that knows the answer for this principal.
    """)


@pytest.fixture
def manifest_file(tmp_path):
    path = tmp_path / "catalogue_recon" / "SKILL.md"
    path.parent.mkdir()
    path.write_text(MANIFEST, encoding="utf-8")
    return path


def write(tmp_path, text, name="SKILL.md"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


class TestLoading:
    def test_identity_comes_from_skill_id(self, manifest_file):
        assert load_skill(manifest_file).name == "catalogue_recon"

    def test_a_flat_manifest_needs_no_skill_block(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: flat
            allowed_tools: [alpha]
            when_to_use: For flat manifests.
            ---
            Body.
            """)
        assert load_skill(path).name == "flat"

    def test_the_version_is_carried(self, manifest_file):
        assert load_skill(manifest_file).version == "0.1.0"

    def test_a_directory_resolves_to_its_skill_md(self, manifest_file):
        assert load_skill(manifest_file.parent).name == "catalogue_recon"

    def test_a_manifest_is_frozen(self, manifest_file):
        manifest = load_skill(manifest_file)
        with pytest.raises(Exception):
            manifest.name = "something else"

    def test_available_skills_lists_a_tree(self, manifest_file):
        found = available_skills(manifest_file.parent.parent)
        assert [p.parent.name for p in found] == ["catalogue_recon"]


class TestTheClosedSet:
    def test_it_is_read_in_file_order(self, manifest_file):
        assert load_skill(manifest_file).allowed_tools == (
            "catalog_search_assets", "catalog_get_asset", "Read",
        )

    def test_a_trailing_question_mark_means_optional(self, manifest_file):
        assert load_skill(manifest_file).optional_tools == {"Read"}

    def test_yaml_comments_are_not_part_of_a_tool_name(self, manifest_file):
        assert "catalog_search_assets" in load_skill(manifest_file).allowed_tools


class TestResolvingAgainstWhatWasDiscovered:
    def test_a_namespaced_bridge_name_matches_the_bare_one(self, manifest_file):
        resolved = load_skill(manifest_file).resolve([
            "mcp.catalog_search_assets", "mcp.catalog_get_asset", "mcp.other",
        ])
        assert resolved == ["mcp.catalog_search_assets", "mcp.catalog_get_asset"]

    def test_the_order_is_the_manifests(self, manifest_file):
        resolved = load_skill(manifest_file).resolve([
            "mcp.catalog_get_asset", "mcp.catalog_search_assets",
        ])
        assert resolved == ["mcp.catalog_search_assets", "mcp.catalog_get_asset"]

    def test_a_tool_not_offered_is_a_refusal_not_a_narrowing(self, manifest_file):
        """THE test. A silently narrowed closed set is an agent that
        answers the question from memory instead of from the catalogue."""
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(manifest_file).resolve(["mcp.catalog_search_assets"])
        assert "catalog_get_asset" in str(exc.value)

    def test_the_refusal_names_every_missing_tool_at_once(self, manifest_file):
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(manifest_file).resolve(["mcp.unrelated"])
        message = str(exc.value)
        assert "catalog_search_assets" in message
        assert "catalog_get_asset" in message

    def test_the_refusal_says_what_was_actually_discovered(self, manifest_file):
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(manifest_file).resolve(["mcp.unrelated"])
        assert "mcp.unrelated" in str(exc.value)

    def test_nothing_discovered_refuses_rather_than_returning_empty(self, manifest_file):
        with pytest.raises(SkillToolsUnavailable):
            load_skill(manifest_file).resolve([])

    def test_an_optional_tool_may_be_absent(self, manifest_file):
        resolved = load_skill(manifest_file).resolve([
            "mcp.catalog_search_assets", "mcp.catalog_get_asset",
        ])
        assert "Read" not in resolved

    def test_an_optional_tool_is_taken_when_present(self, manifest_file):
        resolved = load_skill(manifest_file).resolve([
            "mcp.catalog_search_assets", "mcp.catalog_get_asset", "Read",
        ])
        assert resolved[-1] == "Read"

    def test_all_optional_and_none_present_still_refuses(self, tmp_path):
        """An empty closed set is the failure, however it was reached."""
        path = write(tmp_path, """\
            ---
            name: all-optional
            allowed_tools: ["alpha?", "beta?"]
            when_to_use: Nothing required.
            ---
            Body.
            """)
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(path).resolve(["mcp.gamma"])
        assert "no tools at all" in str(exc.value)

    def test_an_ambiguous_name_is_a_refusal_not_a_coin_flip(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: ambiguous
            allowed_tools: [search]
            when_to_use: Two servers, one name.
            ---
            Body.
            """)
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(path).resolve(["a.search", "b.search"])
        assert "matches 2" in str(exc.value)


class TestTheRefusals:
    def test_a_file_without_frontmatter(self, tmp_path):
        path = write(tmp_path, "# Just a heading\n\nAnd a paragraph.\n")
        with pytest.raises(SkillManifestError) as exc:
            load_skill(path)
        assert "frontmatter" in str(exc.value)

    def test_a_missing_file(self, tmp_path):
        with pytest.raises(SkillManifestError):
            load_skill(tmp_path / "nope.md")

    def test_unreadable_yaml_names_the_parser_error(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: broken
            allowed_tools: [unterminated
            ---
            Body.
            """)
        with pytest.raises(SkillManifestError) as exc:
            load_skill(path)
        assert "unreadable frontmatter" in str(exc.value)

    def test_no_allowed_tools_is_a_refusal(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: open-season
            when_to_use: Anything at all.
            ---
            Body.
            """)
        with pytest.raises(SkillManifestError) as exc:
            load_skill(path)
        assert "allowed_tools" in str(exc.value)

    def test_an_empty_allowed_tools_is_a_refusal(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: empty
            allowed_tools: []
            when_to_use: Nothing.
            ---
            Body.
            """)
        with pytest.raises(SkillManifestError) as exc:
            load_skill(path)
        assert "closed set of nothing" in str(exc.value)

    def test_a_manifest_that_tells_the_model_nothing(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: silent
            allowed_tools: [alpha]
            ---
            """)
        with pytest.raises(SkillManifestError) as exc:
            load_skill(path)
        assert "nothing to tell the model" in str(exc.value)

    def test_every_problem_arrives_in_one_message(self, tmp_path):
        path = write(tmp_path, """\
            ---
            allowed_tools: [alpha, alpha]
            grounding: "not a mapping"
            when_to_use: Two problems and a third.
            ---
            Body.
            """)
        with pytest.raises(SkillManifestError) as exc:
            load_skill(path)
        message = str(exc.value)
        assert "skill_id" in message
        assert "twice" in message
        assert "grounding" in message

    def test_a_duplicate_tool_is_named(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: dup
            allowed_tools: [alpha, alpha]
            when_to_use: Twice.
            ---
            Body.
            """)
        with pytest.raises(SkillManifestError) as exc:
            load_skill(path)
        assert "'alpha' twice" in str(exc.value)

    def test_a_skill_key_holding_a_list(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: wrong-shape
            skill: [a, b]
            ---
            Body.
            """)
        with pytest.raises(SkillManifestError) as exc:
            load_skill(path)
        assert "mapping" in str(exc.value)


class TestThePrompt:
    def test_the_body_reaches_the_model(self, manifest_file):
        assert "only thing that knows the answer" in load_skill(manifest_file).prompt

    def test_the_operational_fields_reach_the_model(self, manifest_file):
        prompt = load_skill(manifest_file).prompt
        assert "Before any orchestration skill." in prompt
        assert "Never invent an asset id." in prompt
        assert "Every row cites the asset id" in prompt

    def test_the_inputs_mapping_is_rendered_readably(self, manifest_file):
        assert "- mission: string" in load_skill(manifest_file).prompt

    def test_the_output_contract_is_last(self, manifest_file):
        manifest = load_skill(manifest_file)
        assert manifest.output_contract.startswith("A table")
        assert manifest.prompt.rstrip().endswith(manifest.output_contract)

    def test_a_field_the_harness_never_heard_of_still_reaches_the_model(self, tmp_path):
        """A manifest is content. The harness is not the authority on
        which of a platform's operational fields matter."""
        path = write(tmp_path, """\
            ---
            name: novel
            allowed_tools: [alpha]
            when_to_use: Something.
            escalation_path: Hand to a duty analyst before disposition.
            ---
            Body.
            """)
        prompt = load_skill(path).prompt
        assert "Escalation path: Hand to a duty analyst" in prompt

    def test_the_structural_keys_are_not_repeated_as_prose(self, manifest_file):
        assert "allowed_tools" not in load_skill(manifest_file).prompt

    def test_the_skill_is_named_at_the_top(self, manifest_file):
        assert load_skill(manifest_file).prompt.startswith("Skill: catalogue_recon")


class TestGroundingBlock:
    def test_it_is_carried_but_not_interpreted(self, manifest_file):
        grounding = load_skill(manifest_file).grounding
        assert grounding["identifier_pattern"] == r"\b[a-z]+\.[0-9a-f]{4,}\b"
        assert grounding["ignore"] == ["example.dead"]

    def test_absence_is_none_and_not_a_default_grammar(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: ungrounded
            allowed_tools: [alpha]
            when_to_use: Something.
            ---
            Body.
            """)
        assert load_skill(path).grounding is None


class TestSdkImport:
    """What the platform is called to `import`, said by the platform.

    The framework drives whatever platform it is pointed at, so it cannot
    know this name — and it used to, as a constant in
    `core.runtime.swarm` reading `import taipan`. Here it is content, like
    the tool names and the grounding grammar beside it.
    """

    def test_a_declared_name_is_carried(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: with-sdk
            allowed_tools: [alpha]
            sdk_import: acme
            when_to_use: Something.
            ---
            Body.
            """)
        assert load_skill(path).sdk_import == "acme"

    def test_absence_is_empty_and_not_a_guess(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: no-sdk
            allowed_tools: [alpha]
            when_to_use: Something.
            ---
            Body.
            """)
        assert load_skill(path).sdk_import == ""

    def test_it_is_structural_and_not_repeated_as_prose(self, tmp_path):
        """It reaches the model through the rung sentence, once. Rendered
        as prose as well, a manifest would be telling the model to import
        something in a paragraph that is not the instruction to do so."""
        path = write(tmp_path, """\
            ---
            name: with-sdk
            allowed_tools: [alpha]
            sdk_import: acme
            when_to_use: Something.
            ---
            Body.
            """)
        assert "sdk_import" not in load_skill(path).prompt

    def test_it_travels_in_a_skill_block_too(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: with-sdk
            skill:
              allowed_tools: [alpha]
              sdk_import: acme
              when_to_use: Something.
            ---
            Body.
            """)
        assert load_skill(path).sdk_import == "acme"

    def test_a_non_string_is_refused_and_not_coerced(self, tmp_path):
        """`import ['acme']` is a line a model will write if it is shown."""
        path = write(tmp_path, """\
            ---
            name: bad-sdk
            allowed_tools: [alpha]
            sdk_import: [acme]
            when_to_use: Something.
            ---
            Body.
            """)
        with pytest.raises(SkillManifestError) as exc:
            load_skill(path)
        assert "sdk_import" in str(exc.value)


class TestTheCodePlaneGate:
    """`run_shell` and `run_python` never reach a hosted mission by accident.

    A manifest whose closed set names a tool that runs code the *model*
    composed has to say `sandbox: bwrap` beside it, and the bus it runs
    on has to actually be bwrap. Both halves, because either one alone
    is a mission that looks governed and is not: a declaration nobody
    checks against the host, or a host nobody asked about.

    The hazard is the one TAIPAN's `HOSTED_SDK_CODE_PLANE_DESIGN.md`
    names: a governed mission that can run arbitrary code on the host
    without isolation.
    """

    def shell_skill(self, tmp_path, extra=""):
        return write(tmp_path, f"""\
            ---
            name: code-plane
            allowed_tools: [governed_read, run_shell_command]
            when_to_use: Something that needs a shell.
            {extra}
            ---
            Body.
            """)

    # ── the set is derived, not typed ───────────────────────────────────

    def test_the_code_plane_set_is_derived_from_the_scopes(self):
        """Not a hand-list of names. A fourth tool that asks for
        `shell.exec` tomorrow is a code plane the day it is registered,
        without anyone remembering to come back here."""
        derived = {
            d.tool_name for d in ALL_DESCRIPTORS
            if (set(d.required_scopes or ())
                | {s for v in (d.action_scopes or {}).values() for s in v})
            & CODE_PLANE_SCOPES
        }
        assert set(code_plane_tools()) == derived

    def test_the_three_tools_that_run_code_today_are_in_it(self):
        assert set(code_plane_tools()) == {
            "run_shell_command", "run_python_code", "install_project",
        }

    def test_each_one_carries_the_scopes_that_put_it_there(self):
        assert code_plane_tools()["install_project"] == (
            "pip.install", "python.exec")

    def test_a_tool_that_does_not_run_the_models_code_is_not_in_it(self):
        """`verify` ends in a subprocess too, and is deliberately out:
        the command it runs is the one the repository configured."""
        assert "fs" not in code_plane_tools()
        assert "verify" not in code_plane_tools()

    # ── the declaration half ────────────────────────────────────────────

    def test_a_code_plane_tool_without_a_declaration_is_refused(
            self, tmp_path):
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(self.shell_skill(tmp_path)).resolve(
                ["governed_read", "run_shell_command"])
        assert "run_shell_command" in str(exc.value)

    def test_the_refusal_names_the_missing_declaration_and_the_fix(
            self, tmp_path):
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(self.shell_skill(tmp_path)).resolve(
                ["governed_read", "run_shell_command"])
        message = str(exc.value)
        assert "declares no `sandbox:`" in message
        assert "add `sandbox: bwrap`" in message
        assert "take the tool out of `allowed_tools`" in message

    def test_the_refusal_names_every_code_plane_tool_at_once(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: all-three
            allowed_tools:
              - run_shell_command
              - run_python_code
              - install_project
            when_to_use: Everything at once.
            ---
            Body.
            """)
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(path).resolve(
                ["run_shell_command", "run_python_code", "install_project"])
        message = str(exc.value)
        assert "run_shell_command" in message
        assert "run_python_code" in message
        assert "install_project" in message

    def test_a_namespaced_spelling_is_caught_too(self, tmp_path):
        """A code plane reached through a bridge is still a code plane,
        and `same_tool` is the harness's one answer to that."""
        path = write(tmp_path, """\
            ---
            name: bridged
            allowed_tools: [mcp.run_python_code]
            when_to_use: Through a server.
            ---
            Body.
            """)
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(path).resolve(["mcp.run_python_code"])
        assert "mcp.run_python_code" in str(exc.value)

    def test_an_optional_code_plane_tool_still_needs_the_declaration(
            self, tmp_path):
        """DECIDED: `?` marks what the host may not offer, not what the
        manifest may not do. Gating on what was discovered would make
        one file governed on one host and ungoverned on the next."""
        path = write(tmp_path, """\
            ---
            name: maybe-shell
            allowed_tools: [governed_read, "run_shell_command?"]
            when_to_use: A shell if there is one.
            ---
            Body.
            """)
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(path).resolve(["governed_read"])
        assert "run_shell_command" in str(exc.value)

    def test_the_declaration_is_checked_even_when_no_bus_was_named(
            self, tmp_path):
        """It reads the manifest and nothing else, so a library caller
        that passes no sandbox is not exempt from it."""
        with pytest.raises(SkillToolsUnavailable):
            load_skill(self.shell_skill(tmp_path)).resolve(
                ["governed_read", "run_shell_command"])

    def test_sandbox_none_does_not_satisfy_a_code_plane_manifest(
            self, tmp_path):
        path = self.shell_skill(tmp_path, extra="sandbox: none")
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(path).resolve(
                ["governed_read", "run_shell_command"], sandbox="none")
        assert "declares `sandbox: none`" in str(exc.value)

    def test_declared_and_isolated_resolves(self, tmp_path):
        path = self.shell_skill(tmp_path, extra="sandbox: bwrap")
        assert load_skill(path).resolve(
            ["governed_read", "run_shell_command"], sandbox="bwrap",
        ) == ["governed_read", "run_shell_command"]

    # ── the isolation half ──────────────────────────────────────────────

    def test_declared_bwrap_on_an_unisolated_bus_is_refused(self, tmp_path):
        """The manifest asked for isolation and did not get it. A hosted
        platform must not learn that from the transcript."""
        path = self.shell_skill(tmp_path, extra="sandbox: bwrap")
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(path).resolve(
                ["governed_read", "run_shell_command"], sandbox="none")
        message = str(exc.value)
        assert "declares `sandbox: bwrap`" in message
        assert "the tool bus is running 'none'" in message
        assert "the isolation it asked for is not" in message

    def test_the_isolation_half_holds_without_a_code_plane_tool(
            self, tmp_path):
        """`sandbox: bwrap` is a statement about the run, not a property
        of the tool list: a manifest that asked for it and was given
        `none` is refused whatever its closed set holds."""
        path = write(tmp_path, """\
            ---
            name: isolated-anyway
            allowed_tools: [governed_read]
            sandbox: bwrap
            when_to_use: Isolation for its own sake.
            ---
            Body.
            """)
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(path).resolve(["governed_read"], sandbox="none")
        assert "isolation" in str(exc.value)

    def test_a_caller_that_did_not_say_is_not_told_it_is_unisolated(
            self, tmp_path):
        """Unstated is not `none`. A library caller holding no bus is
        told nothing rather than told something false."""
        path = self.shell_skill(tmp_path, extra="sandbox: bwrap")
        assert load_skill(path).resolve(
            ["governed_read", "run_shell_command"],
        ) == ["governed_read", "run_shell_command"]

    def test_an_isolation_refusal_does_not_lecture_about_the_closed_set(
            self, tmp_path):
        """The discovered list and the sentence about narrowing answer a
        missing *tool*. On a refusal that is only about isolation they
        point the reader at the wrong file."""
        path = self.shell_skill(tmp_path, extra="sandbox: bwrap")
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(path).resolve(
                ["governed_read", "run_shell_command"], sandbox="none")
        assert "not narrowed" not in str(exc.value)

    def test_both_kinds_of_problem_arrive_in_one_refusal(self, tmp_path):
        """The idiom of this loader: an operator edits the file once."""
        path = write(tmp_path, """\
            ---
            name: two-problems
            allowed_tools: [run_shell_command, catalog_get_asset]
            when_to_use: A shell and a missing tool.
            ---
            Body.
            """)
        with pytest.raises(SkillToolsUnavailable) as exc:
            load_skill(path).resolve(["run_shell_command"])
        message = str(exc.value)
        assert "add `sandbox: bwrap`" in message
        assert "catalog_get_asset" in message
        assert "not narrowed" in message

    # ── the ordinary manifest is untouched ──────────────────────────────

    def test_a_manifest_with_no_code_plane_tools_is_unaffected(
            self, manifest_file):
        assert load_skill(manifest_file).resolve(
            ["mcp.catalog_search_assets", "mcp.catalog_get_asset"],
            sandbox="none",
        ) == ["mcp.catalog_search_assets", "mcp.catalog_get_asset"]

    def test_sandbox_none_there_is_accepted_and_inert(self, tmp_path):
        """A manifest may say out loud that it asked for nothing."""
        path = write(tmp_path, """\
            ---
            name: plainly-unisolated
            allowed_tools: [governed_read]
            sandbox: none
            when_to_use: No code, no isolation.
            ---
            Body.
            """)
        manifest = load_skill(path)
        assert manifest.sandbox == "none"
        assert manifest.resolve(["governed_read"], sandbox="none") == [
            "governed_read"]

    # ── the field itself ────────────────────────────────────────────────

    def test_the_declared_value_is_carried(self, tmp_path):
        path = self.shell_skill(tmp_path, extra="sandbox: bwrap")
        assert load_skill(path).sandbox == "bwrap"

    def test_absence_is_empty_and_is_not_none(self, manifest_file):
        assert load_skill(manifest_file).sandbox == ""

    def test_it_travels_in_a_skill_block_too(self, tmp_path):
        path = write(tmp_path, """\
            ---
            name: blocked
            skill:
              allowed_tools: [run_shell_command]
              sandbox: bwrap
              when_to_use: Something.
            ---
            Body.
            """)
        assert load_skill(path).resolve(
            ["run_shell_command"], sandbox="bwrap") == ["run_shell_command"]

    def test_a_value_nobody_implements_is_refused_at_load(self, tmp_path):
        """`sandbox: firejail` asks for isolation this framework does
        not have, and reading it as good enough is how a declaration
        becomes decoration."""
        path = self.shell_skill(tmp_path, extra="sandbox: firejail")
        with pytest.raises(SkillManifestError) as exc:
            load_skill(path)
        message = str(exc.value)
        assert "'firejail'" in message
        assert "`bwrap`" in message

    def test_the_refusal_for_a_bad_value_joins_the_others(self, tmp_path):
        path = write(tmp_path, """\
            ---
            allowed_tools: [alpha, alpha]
            sandbox: 3
            when_to_use: Three problems.
            ---
            Body.
            """)
        with pytest.raises(SkillManifestError) as exc:
            load_skill(path)
        message = str(exc.value)
        assert "skill_id" in message
        assert "twice" in message
        assert "`sandbox:`" in message

    def test_the_declaration_reaches_the_model(self, tmp_path):
        """The model is told it is inside bwrap. Network is denied in
        there, and an agent that has not been told reads ENETUNREACH as
        a broken tool and spends a turn retrying it."""
        path = self.shell_skill(tmp_path, extra="sandbox: bwrap")
        assert "Sandbox: bwrap" in load_skill(path).prompt


class TestTheSandboxSeam:
    """`sandbox_name` — how a manifest finds out what it is running on.

    Deliberately the smallest seam available: the runner a `ToolBus`
    will wrap a subprocess in. A flag that did not take effect and a
    bwrap that is not installed have to look identical here, because to
    the manifest that asked for isolation they are the same thing.
    """

    def test_a_none_bus_is_unisolated_and_says_so(self):
        # Explicit, because a bare ``ToolBus()`` is bwrap wherever bubblewrap
        # exists (0.9.0): the unisolated case has to be asked for by name.
        assert sandbox_name(ToolBus(sandbox=NoneSandbox())) == "none"

    def test_a_bare_bus_names_whatever_select_sandbox_chose(self):
        from core.tools.sandbox import select_sandbox
        assert sandbox_name(ToolBus()) == select_sandbox()[1]

    @patch("core.tools.sandbox.shutil.which", return_value="/usr/bin/bwrap")
    def test_a_bwrap_bus_is_named_bwrap(self, _which):
        assert sandbox_name(ToolBus(sandbox=BwrapSandbox())) == "bwrap"

    def test_nothing_at_all_is_unstated_rather_than_unisolated(self):
        """`""` is not `"none"`: one is silence, the other is an answer."""
        assert sandbox_name(None) == ""

    def test_a_backend_nobody_has_written_yet_names_itself(self):
        class GvisorSandbox:
            pass

        class Bus:
            sandbox = GvisorSandbox()

        assert sandbox_name(Bus()) == "gvisor"


# ---------------------------------------------------------------------------
# Against the real files this format was read off
# ---------------------------------------------------------------------------

#: A directory of ``<name>/SKILL.md`` manifests written by a real
#: deployment, named by the operator who has one. It used to be one
#: developer's absolute path, which made the check silently machine-shaped:
#: green on that laptop, skipped everywhere else, and nothing in the skip
#: reason told anyone what to install or export to change that.
SKILLS_DIR_ENV = "TAIPAN_SKILLS_DIR"

_configured = (os.getenv(SKILLS_DIR_ENV) or "").strip()
TAIPAN_SKILLS = Path(_configured).expanduser() if _configured else None

real_skills = pytest.mark.skipif(
    TAIPAN_SKILLS is None or not TAIPAN_SKILLS.is_dir(),
    reason=f"set {SKILLS_DIR_ENV} to a directory of <name>/SKILL.md manifests "
           f"a real deployment ships; there is no default path",
)


def _real_manifests():
    """Every manifest under the configured directory, or none at all."""
    return sorted(TAIPAN_SKILLS.glob("*/SKILL.md")) if TAIPAN_SKILLS else []


@real_skills
class TestAgainstRealManifests:
    """Read-only, and the reason the format is not a guess.

    These five files are not fixtures — they are the manifests a real
    deployment ships, written before this loader existed. A parser that
    only reads its own fixture is a parser that has agreed with itself.
    """

    @pytest.mark.parametrize("path", _real_manifests(),
                             ids=lambda p: p.parent.name)
    def test_it_loads_with_a_closed_set_and_a_prompt(self, path):
        manifest = SkillManifest.from_file(path)
        assert manifest.name
        assert manifest.allowed_tools
        assert len(manifest.prompt) > 1000

    @pytest.mark.parametrize("path", _real_manifests(),
                             ids=lambda p: p.parent.name)
    def test_the_densest_rules_survive_the_round_trip(self, path):
        """The point of loading these at all: the operational knowledge
        in them is what none of it reaching the model was costing."""
        manifest = SkillManifest.from_file(path)
        assert manifest.output_contract
        assert "PHILOSOPHY" in manifest.prompt or "policy" in manifest.prompt.lower()

    def test_a_named_directory_of_skills_refuses_to_guess(self):
        with pytest.raises(SkillManifestError) as exc:
            load_skill(TAIPAN_SKILLS)
        assert "catalogue_recon" in str(exc.value)
