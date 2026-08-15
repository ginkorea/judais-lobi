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

import pytest

from core.runtime.skills import (
    SkillManifest,
    SkillManifestError,
    SkillToolsUnavailable,
    available_skills,
    load_skill,
)

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
