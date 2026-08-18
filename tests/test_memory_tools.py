# tests/test_memory_tools.py — memory is a plane, and it is governed like one

"""The two tools on the bus: who may call them, and what comes back.

The claim this file exists to hold is that memory is **not a side door**.
A recall and a write go out through the same
:class:`~core.tools.bus.ToolBus` as a filesystem read: the capability engine
sees them, the audit log records them, and the result comes back in the
executor's ordinary ``(exit_code, stdout, stderr)`` shape — so nothing new
appears on the wire and a note the model quotes is an ordinary tool result.

The split is the interesting part.  ``memory.read`` is in SAFE because a
recall reaches nothing this deployment was not already told; ``memory.write``
is in DEV because pinning a sentence into every future system turn is a
durable effect on later runs.  A run under the default profile may consult
what it knows and may not change what it will be told next time.
"""

import json

import pytest

from core.contracts.schemas import ProfileMode
from core.memory.bank import MemoryBank
from core.policy.profiles import (
    PROFILE_SCOPES, lowest_profile_for_scope, policy_for_profile,
)
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import (
    ALL_DESCRIPTORS, MEMORY_RECALL_DESCRIPTOR, MEMORY_RECALL_TOOL,
    MEMORY_WRITE_DESCRIPTOR, MEMORY_WRITE_TOOL,
)
from core.tools.sandbox import NoneSandbox


def bus_under(profile):
    return ToolBus(
        capability_engine=CapabilityEngine(policy_for_profile(profile)),
        sandbox=NoneSandbox())


@pytest.fixture
def bank(tmp_path):
    return MemoryBank(tmp_path / "bank", principal="alice")


@pytest.fixture
def dev(bank):
    bus = bus_under(ProfileMode.DEV)
    bank.register_on(bus, run_id="run-1")
    return bus


class TestTheDescriptorsSayWhatTheyNeed:
    def test_both_are_shipped_descriptors(self):
        names = [descriptor.tool_name for descriptor in ALL_DESCRIPTORS]
        assert MEMORY_RECALL_TOOL in names and MEMORY_WRITE_TOOL in names

    def test_recall_asks_for_memory_read(self):
        assert MEMORY_RECALL_DESCRIPTOR.required_scopes == ["memory.read"]

    def test_write_asks_for_memory_write_on_every_action(self):
        assert set(MEMORY_WRITE_DESCRIPTOR.action_scopes) == {
            "add", "replace", "delete"}
        for scopes in MEMORY_WRITE_DESCRIPTOR.action_scopes.values():
            assert scopes == ["memory.write"]

    def test_neither_asks_for_the_network(self):
        for descriptor in (MEMORY_RECALL_DESCRIPTOR, MEMORY_WRITE_DESCRIPTOR):
            assert descriptor.requires_network is False
            assert descriptor.sandbox_profile.allow_network is False

    def test_the_write_schema_makes_reason_required(self):
        required = MEMORY_WRITE_DESCRIPTOR.input_schema["required"]
        assert "reason" in required and "action" in required

    def test_the_recall_description_says_nothing_is_automatic(self):
        assert "automatically" in MEMORY_RECALL_DESCRIPTOR.description
        assert "DATED" in MEMORY_RECALL_DESCRIPTOR.description


class TestReadingIsSafeAndWritingIsNot:
    def test_memory_read_is_granted_by_the_default_profile(self):
        assert "memory.read" in PROFILE_SCOPES[ProfileMode.SAFE]
        assert lowest_profile_for_scope("memory.read") is ProfileMode.SAFE

    def test_memory_write_is_granted_by_dev(self):
        assert "memory.write" in PROFILE_SCOPES[ProfileMode.DEV]
        assert lowest_profile_for_scope("memory.write") is ProfileMode.DEV

    def test_a_safe_run_may_recall(self, bank):
        bank.add_note("alpha", "a remembered thing")
        bus = bus_under(ProfileMode.SAFE)
        bank.register_on(bus)
        result = bus.dispatch(MEMORY_RECALL_TOOL, query="alpha")
        assert result.exit_code == 0
        assert "alpha" in result.stdout

    def test_a_safe_run_may_not_write(self, bank):
        bus = bus_under(ProfileMode.SAFE)
        bank.register_on(bus)
        result = bus.dispatch(MEMORY_WRITE_TOOL, action="add", label="k",
                              kind="fact", body="b", reason="r", source="s")
        assert result.exit_code == -1
        assert json.loads(result.stderr)["error"] == "capability_denied"
        assert bank.blocks() == []

    def test_the_refusal_names_the_profile_that_would_grant_it(self, bank):
        bus = bus_under(ProfileMode.SAFE)
        bank.register_on(bus)
        result = bus.dispatch(MEMORY_WRITE_TOOL, action="add", label="k",
                              reason="r", source="s", kind="fact", body="b")
        assert "dev" in json.loads(result.stderr)["message"]

    def test_a_dev_run_may_write(self, bank, dev):
        result = dev.dispatch(MEMORY_WRITE_TOOL, action="add", label="style",
                              kind="preference", body="Be brief.",
                              reason="asked twice", source="r3")
        assert result.exit_code == 0, result.stderr
        assert [block.label for block in bank.blocks()] == ["style"]


class TestWhatComesBackIsAnOrdinaryToolResult:
    def test_a_recall_is_stdout_and_a_zero(self, bank, dev):
        bank.add_note("alpha", "a remembered thing")
        result = dev.dispatch(MEMORY_RECALL_TOOL, query="alpha")
        assert (result.exit_code, result.stderr) == (0, "")
        assert "a remembered thing" in result.stdout

    def test_a_refused_write_is_stderr_and_a_one(self, dev):
        result = dev.dispatch(MEMORY_WRITE_TOOL, action="add", label="k",
                              kind="fact", body="b", source="s")
        assert result.exit_code == 1
        assert "reason is required" in result.stderr

    def test_the_action_reaches_the_bank(self, bank, dev):
        dev.dispatch(MEMORY_WRITE_TOOL, action="add", label="k", kind="fact",
                     body="one", reason="r", source="s")
        dev.dispatch(MEMORY_WRITE_TOOL, action="replace", label="k",
                     kind="fact", body="two", reason="r", source="s")
        assert bank.blocks()[0].body == "two"
        dev.dispatch(MEMORY_WRITE_TOOL, action="delete", label="k",
                     reason="done")
        assert bank.blocks() == []

    def test_the_run_id_is_stamped_by_the_harness_not_the_model(self, bank,
                                                                dev):
        dev.dispatch(MEMORY_WRITE_TOOL, action="add", label="k", kind="fact",
                     body="b", reason="r", source="r3")
        assert bank.blocks()[0].run_id == "run-1"

    def test_a_dispatch_is_audited_like_any_other(self, bank, tmp_path):
        """The real logger, not a stand-in: the claim is that memory goes
        through the same path, and a fake audit sink would only prove that
        a fake was called."""
        from core.policy.audit import AuditLogger

        log = tmp_path / "audit.jsonl"
        bus = ToolBus(
            capability_engine=CapabilityEngine(
                policy_for_profile(ProfileMode.DEV)),
            sandbox=NoneSandbox(), audit=AuditLogger(path=log))
        bank.register_on(bus)
        bus.dispatch(MEMORY_RECALL_TOOL, query="alpha")
        bus.dispatch(MEMORY_WRITE_TOOL, action="add", label="k", kind="fact",
                     body="b", reason="r", source="s")
        written = [json.loads(line) for line in
                   log.read_text().splitlines() if line.strip()]
        assert [entry["tool_name"] for entry in written] == [
            MEMORY_RECALL_TOOL, MEMORY_WRITE_TOOL]


class TestRegistrationIsPerRunAndDoesNotShadow:
    def test_both_names_go_on(self, bank):
        bus = bus_under(ProfileMode.DEV)
        assert bank.register_on(bus) == [MEMORY_RECALL_TOOL,
                                         MEMORY_WRITE_TOOL]
        assert bus.get_descriptor(MEMORY_RECALL_TOOL) is not None
        assert bus.get_descriptor(MEMORY_WRITE_TOOL) is not None

    def test_a_second_registration_adds_nothing_and_claims_nothing(self,
                                                                   bank):
        """A sub-mission shares its parent's plane.  A child that
        re-registered and then withdrew would take the tools away from the
        turn it is a step of."""
        bus = bus_under(ProfileMode.DEV)
        bank.register_on(bus)
        assert bank.register_on(bus) == []

    def test_the_names_are_the_ones_the_run_offers(self, bank):
        assert bank.tool_names() == [MEMORY_RECALL_TOOL, MEMORY_WRITE_TOOL]
