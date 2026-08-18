# tests/test_campaign_run.py — a plan of missions, dispatched as child Runs

"""What a campaign is now that it runs on :class:`~core.runtime.run.Run`.

February's ``CampaignOrchestrator`` walked a plan's DAG through the coding
kernel's task dispatcher.  It had no run store, no ``--approval``, no
supervisor, nothing on the wire and no resume — and beside it
:mod:`core.runtime.swarm` walked a plan's DAG through ``Run`` with all
five.  :class:`~core.runtime.campaign.CampaignRunner` is that second loop
with the plan supplied by a **person** instead of a planner, so what is
asserted here is deliberately only what a campaign adds:

* the **plan** somebody wrote is the plan that runs — in DAG order, never
  redrawn, with each step's ``branch`` on the wire and the plan itself on
  the first ``step_started`` exactly as the swarm's is;
* **artifacts** hand off: a step's declared inputs are copied out of the
  steps that produced them, its declared exports are collected after, and
  the ``artifacts`` field on each step's ``step_started`` says which —
  per step, which is why it is carried by name and not by the queue;
* **approval**: an unapproved plan ends the run at ``awaiting_approval``
  holding the plan, and ``--approval`` continues it.  One mechanism, the
  durable one;
* **least privilege**: each step is narrowed to its own effective scopes,
  so a step that never asked for ``fs.write`` cannot write;
* **resume**: a campaign killed after its first step continues at the
  second, with the first not run again — and it resumes *as a campaign*,
  because the plan it was approved for is on its record.

Nothing here builds a second idea of what a run is: the six objects come
from :func:`tests.test_run.six`, and the conformance check is
``tests/test_contract.py``'s own.
"""

import asyncio
import json
import re
import threading
import time
from pathlib import Path

import pytest

from core.contracts.campaign import ArtifactRef, CampaignPlan, MissionStep
from core.contracts.schemas import ProfileMode
from core.durable import RunStore
from core.policy.profiles import policy_for_profile
from core.runtime.approvals import ApprovalStore, resolve
from core.runtime.campaign import (
    CAMPAIGN_TOOL, CampaignRefused, CampaignRunner, TaskTemplate,
    campaign_meta, load_template, plan_digest, plan_from_file,
    resumed_campaign, templates_of,
)
from core.runtime.contract import (
    GATE_REQUESTED, MISSION_FINISHED, MISSION_STARTED, STEP_STARTED,
)
from core.runtime.run import Model, Run, Store, ToolPlane
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from tests.test_contract import _faults
from tests.test_run import six

#: The template a step names.  A real one — the shape of the file the
#: analyst pack ships — because the vocabulary a plan may pick from is the
#: installed templates and a made-up name is exactly what the validator
#: refuses.
REPORTING = TaskTemplate(name="find_and_report", skill="analyst",
                         description="Work out what the data says, then "
                                     "leave the answer somewhere.",
                         shape=("act — run the computation",))


# ── the plane these campaigns run on ────────────────────────────────────────


def bus(calls=None):
    """Two tools: one that writes a file, one that reads one.

    Under DEV, which carries both ``fs.read`` and ``fs.write``, so that
    every refusal below is a **step's** narrowing and never the profile's:
    a test where the profile did the denying would prove nothing about
    effective scopes.
    """
    engine = CapabilityEngine(policy_for_profile(ProfileMode.DEV))
    engine.set_profile(ProfileMode.DEV)
    plane_bus = ToolBus(capability_engine=engine)

    def write_file(path, text="", **_kw):
        if calls is not None:
            calls.append(("write_file", path))
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(text))
        return (0, f"wrote {target.name} ({len(str(text))} bytes)", "")

    def read_file(path, **_kw):
        if calls is not None:
            calls.append(("read_file", path))
        return (0, Path(path).read_text(), "")

    plane_bus.register(
        ToolDescriptor(tool_name="write_file", required_scopes=["fs.write"],
                       description="Writes a file. Second sentence."),
        write_file)
    plane_bus.register(
        ToolDescriptor(tool_name="read_file", required_scopes=["fs.read"],
                       description="Reads a file. Second sentence."),
        read_file)
    return plane_bus


#: Where the executor is told its inputs are, and where its outputs go.
#: Read out of the prompt rather than computed here, because "the step is
#: told the path" is the whole of the handoff contract from the model's
#: side and a test that knew the path another way would not check it.
_IN = re.compile(r"artifacts from earlier steps are in (\S+) —")
_OUT = re.compile(r"into (\S+): ")


def out_dir(text):
    found = _OUT.search(text)
    assert found, f"the step was never told where to write:\n{text}"
    return found.group(1)


def in_dir(text):
    found = _IN.search(text)
    assert found, f"the step was never told where to read:\n{text}"
    return found.group(1)


def tool_call(name, **arguments):
    return json.dumps({"tool": name, "arguments": arguments})


def answered(text):
    return json.dumps({"answer": text})


class Steps:
    """A scripted executor that answers whichever step is asking.

    :mod:`tests.test_run_parallel`'s ``ByStep``, and for its reason: a
    queue cannot be shared by two children running at once, so the reply is
    chosen by *who is asking* — every executor prompt names its step — and
    never by *when*.  A reply may be a callable, which is handed the prompt
    so it can build a path the step was just told about.
    """

    def __init__(self, scripts, nap=0.0):
        self.scripts = {key: list(replies)
                        for key, replies in scripts.items()}
        self.nap = nap
        self.most = 0
        self.seen = []
        self._busy = 0
        self._lock = threading.Lock()

    def __call__(self, messages, **_kw):
        text = "\n".join(str(m.get("content", "")) for m in messages)
        with self._lock:
            self.seen.append(text)
            self._busy += 1
            self.most = max(self.most, self._busy)
        if self.nap:
            time.sleep(self.nap)
        with self._lock:
            self._busy -= 1
            for key, replies in self.scripts.items():
                if f"Step {key} of a plan" in text and replies:
                    reply = replies.pop(0)
                    return reply(text) if callable(reply) else reply
        raise AssertionError(f"nothing scripted for this turn: {text[-300:]}")


class Roles:
    """The gate and the synthesizer, which are serial whatever the steps do.

    A gate turn is answered ``pass``; anything else is the synthesis, and
    it is answered with the step lines it was shown, so an assertion about
    "the answer names each step's result" is about what reached the
    synthesizer rather than about a fixed string.
    """

    def __init__(self, *, passes=True):
        self.passes = passes
        self.seen = []

    def __call__(self, messages, **_kw):
        text = "\n".join(str(m.get("content", "")) for m in messages)
        self.seen.append(text)
        if "Step goal:" in text:
            return json.dumps({"pass": bool(self.passes)})
        body = text.split("Step results:\n", 1)
        return ("Campaign report. " + body[1].split("\n\n")[0]) if len(body) > 1 \
            else "Campaign report."


# ── the plans ───────────────────────────────────────────────────────────────


def step(step_id, description, *, needs=(), takes=(), exports=(),
         scopes=("fs.read", "fs.write"), workflow="find_and_report",
         done="the artifact exists"):
    return MissionStep(
        step_id=step_id, description=description,
        target_workflow=workflow,
        capabilities_required=list(scopes),
        inputs_from=list(needs),
        handoff_artifacts=[ArtifactRef(step_id=producer, artifact_name=name)
                           for producer, name in takes],
        exports=list(exports),
        success_criteria=done,
    )


def fan_out():
    """A → B and A → C, with B and C each reading A's one artifact.

    The shape ``ROADMAP.md`` §2.6b describes and the shape a campaign is
    for: one piece of work whose result two independent pieces both need.
    """
    return CampaignPlan(
        campaign_id="fanout", objective="measure it and write it up twice",
        assumptions=[],
        steps=[
            step("a", "compute the figure", exports=["figures.json"]),
            step("b", "write the short report", needs=["a"],
                 takes=[("a", "figures.json")], exports=["short.md"]),
            step("c", "write the long report", needs=["a"],
                 takes=[("a", "figures.json")], exports=["long.md"]),
        ])


def writes(name, body):
    """A step's two turns: write the named artifact, then report it."""
    return [lambda text: tool_call("write_file",
                                   path=f"{out_dir(text)}/{name}",
                                   text=body),
            answered(f"wrote {name}: {body}")]


def reads_then_writes(source, name, body):
    """A step's three turns: read the handoff, write its own, report."""
    return [lambda text: tool_call("read_file",
                                   path=f"{in_dir(text)}/{source}"),
            lambda text: tool_call("write_file",
                                   path=f"{out_dir(text)}/{name}",
                                   text=body),
            answered(f"wrote {name} from {source}")]


def fan_out_scripts(nap=0.0):
    return Steps({
        "a": writes("figures.json", '{"total": 41}'),
        "b": reads_then_writes("figures.json", "short.md", "total 41"),
        "c": reads_then_writes("figures.json", "long.md", "total is 41"),
    }, nap=nap)


# ── building one ────────────────────────────────────────────────────────────


def campaign(tmp_path, plan, executor, *, records=None, roles=None,
             parallel=1, auto_approve=True, approvals=None, ticket=None,
             run_store=None, run_id="", plane=None, calls=None, **kw):
    """A campaign over the six objects, and the records it emitted."""
    seen = [] if records is None else records
    roles = roles if roles is not None else Roles()
    plane_bus = bus(calls) if plane is None else plane.bus
    built = six(plane_bus, seen)
    built["plane"] = plane if plane is not None else ToolPlane(
        bus=plane_bus, offered=["write_file", "read_file"])
    built["model"] = Model(ask=executor, plain=roles)
    if approvals is not None or run_store is not None:
        built["store"] = Store(runs=run_store, run_id=run_id,
                               approvals=approvals, ticket=ticket)
        built["observer"] = type(built["observer"])(seen.append,
                                                    store=built["store"])
    runner = CampaignRunner(Run(**built), plan,
                            workspace=tmp_path, templates={
                                REPORTING.name: REPORTING},
                            parallel=parallel, auto_approve=auto_approve,
                            **kw)
    return runner, seen


def events(records, event):
    return [record for record in records if record["event"] == event]


def opened(records):
    return events(records, STEP_STARTED)


# ── the plan somebody wrote is the plan that runs ───────────────────────────


class TestThePlanIsDispatchedInDagOrder:

    def test_a_step_runs_after_everything_it_needs(self, tmp_path):
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts())
        runner.run()
        order = [r["branch"] for r in opened(records)]
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")

    def test_a_plan_written_out_of_order_still_runs_in_order(self, tmp_path):
        """A plan file's steps are in whatever order a person typed them.
        The inherited loop pops ``queue[0]`` — the first step, not the
        first *ready* one — so the sort has to happen at the door."""
        plan = fan_out()
        plan.steps = [plan.steps[2], plan.steps[0], plan.steps[1]]
        runner, records = campaign(tmp_path, plan, fan_out_scripts())
        runner.run()
        assert [r["branch"] for r in opened(records)][0] == "a"

    def test_ties_keep_the_order_the_plan_was_written_in(self, tmp_path):
        """What somebody approved is what they read, top to bottom."""
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts())
        runner.run()
        order = [r["branch"] for r in opened(records)]
        assert order.index("b") < order.index("c")

    def test_the_plan_rides_the_first_step_started_and_no_other(self,
                                                                tmp_path):
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts())
        runner.run()
        carrying = [r for r in opened(records) if "plan" in r]
        assert len(carrying) == 1
        assert carrying[0] is opened(records)[0]
        assert [entry["id"] for entry in carrying[0]["plan"]] == \
            ["a", "b", "c"]

    def test_the_plans_rung_names_the_steps_task_template(self, tmp_path):
        """``rung`` says *how* a step gets done. For a plan step that is
        "tool" or "code"; for a campaign step it is the template, which is
        the same kind of fact in the same field."""
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts())
        runner.run()
        plan = [r for r in opened(records) if "plan" in r][0]["plan"]
        assert {entry["rung"] for entry in plan} == {"find_and_report"}

    def test_every_record_says_which_step_it_belongs_to(self, tmp_path):
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts())
        runner.run()
        assert {r["branch"] for r in opened(records)} == {"a", "b", "c"}

    def test_the_indexes_are_one_sequence_with_nothing_used_twice(self,
                                                                  tmp_path):
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts())
        runner.run()
        numbers = [r["index"] for r in opened(records)]
        assert numbers == list(range(len(numbers)))

    def test_a_campaign_plan_is_never_redrawn(self, tmp_path):
        """``ROADMAP.md`` §5.1 invariant 9: the DAG is frozen once
        approved. A failed step ends the dispatch rather than buying a new
        plan — because the plan is what a person said yes to."""
        runner, _records = campaign(tmp_path, fan_out(), fan_out_scripts())
        assert runner._redraw("obj", None, None, {}, None) == []


class TestAPlanThatWillNotRun:
    """Refused at construction, before a model is asked anything."""

    def test_a_cycle_is_refused_by_name(self, tmp_path):
        plan = fan_out()
        plan.steps[0].inputs_from = ["b"]
        with pytest.raises(CampaignRefused, match="campaign_dag_cycle"):
            campaign(tmp_path, plan, fan_out_scripts())

    def test_a_template_nobody_installed_is_refused_by_step(self, tmp_path):
        plan = fan_out()
        plan.steps[1].target_workflow = "no_such_template"
        with pytest.raises(CampaignRefused, match="unknown_workflow:b"):
            campaign(tmp_path, plan, fan_out_scripts())

    def test_the_kernels_own_workflows_are_still_a_vocabulary(self,
                                                              tmp_path):
        """February's plans name ``coding``/``generic``. One runner takes
        both vocabularies rather than one validator per plan dialect."""
        plan = fan_out()
        for entry in plan.steps:
            entry.target_workflow = "generic"
        runner, _records = campaign(tmp_path, plan, fan_out_scripts())
        assert runner is not None

    def test_an_artifact_path_that_escapes_is_refused(self, tmp_path):
        plan = fan_out()
        plan.steps[1].handoff_artifacts = [
            ArtifactRef(step_id="a", artifact_name="../../etc/passwd")]
        with pytest.raises(CampaignRefused, match="unsafe_handoff_path"):
            campaign(tmp_path, plan, fan_out_scripts())


# ── artifacts ───────────────────────────────────────────────────────────────


class TestArtifactsHandOff:

    def test_a_later_step_reads_what_an_earlier_one_wrote(self, tmp_path):
        calls = []
        runner, _records = campaign(tmp_path, fan_out(), fan_out_scripts(),
                                    calls=calls)
        runner.run()
        read = [path for name, path in calls if name == "read_file"]
        assert len(read) == 2
        for path in read:
            assert Path(path).name == "figures.json"
            assert Path(path).read_text() == '{"total": 41}'

    def test_the_copy_lands_in_the_readers_own_handoff_in(self, tmp_path):
        """Copied, not shared. A step reads its own directory, so a step
        that edits what it was given cannot edit its sibling's copy."""
        calls = []
        runner, _records = campaign(tmp_path, fan_out(), fan_out_scripts(),
                                    calls=calls)
        runner.run()
        read = sorted(path for name, path in calls if name == "read_file")
        assert "/steps/b/handoff_in/" in read[0]
        assert "/steps/c/handoff_in/" in read[1]

    def test_each_step_started_says_what_the_step_takes_and_owes(self,
                                                                 tmp_path):
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts())
        runner.run()
        by_branch = {r["branch"]: r.get("artifacts")
                     for r in opened(records) if "artifacts" in r}
        assert by_branch["a"] == {"in": [], "out": ["figures.json"]}
        assert by_branch["b"] == {"in": ["figures.json"], "out": ["short.md"]}
        assert by_branch["c"] == {"in": ["figures.json"], "out": ["long.md"]}

    def test_the_field_rides_the_steps_own_first_record(self, tmp_path):
        """Exactly one ``step_started`` per step carries it: it is an
        announcement, not a state restated on every turn."""
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts())
        runner.run()
        carrying = [r["branch"] for r in opened(records) if "artifacts" in r]
        assert sorted(carrying) == ["a", "b", "c"]

    def test_a_step_that_did_not_write_its_export_failed(self, tmp_path):
        """The campaign's own gate, and it is mechanical: a model that says
        it wrote the report is not evidence that a report exists."""
        scripts = Steps({
            "a": [lambda text: tool_call("write_file",
                                         path=f"{out_dir(text)}/wrong.json",
                                         text="{}"),
                  answered("wrote the figures")],
        })
        plan = CampaignPlan(campaign_id="one", objective="just a",
                            assumptions=[],
                            steps=[step("a", "compute",
                                        exports=["figures.json"])])
        runner, records = campaign(tmp_path, plan, scripts)
        transcript = runner.run()
        assert "figures.json" in transcript.answer or \
            "figures.json" in str(events(records, "answer"))
        assert transcript.outcome == "answered_with_caveat"

    def test_an_export_that_did_arrive_is_readable_afterwards(self,
                                                              tmp_path):
        runner, _records = campaign(tmp_path, fan_out(), fan_out_scripts())
        runner.run()
        assert runner.artifacts_of("a") == ["figures.json"]
        assert runner.artifacts_of("b") == ["short.md"]

    def test_a_step_is_told_the_paths_rather_than_left_to_guess(self,
                                                                tmp_path):
        executor = fan_out_scripts()
        runner, _records = campaign(tmp_path, fan_out(), executor)
        runner.run()
        told = [text for text in executor.seen if "Step b of a plan" in text]
        assert any("handoff_in" in text and "handoff_out" in text
                   for text in told)

    def test_a_declared_input_that_never_arrived_is_named_to_the_step(
            self, tmp_path):
        """Rather than the step being handed an empty directory and
        inventing what should have been in it."""
        plan = CampaignPlan(
            campaign_id="gap", objective="b needs what a never wrote",
            assumptions=[],
            steps=[step("a", "compute"),
                   step("b", "report", needs=["a"],
                        takes=[("a", "figures.json")])])
        scripts = Steps({
            "a": [tool_call("read_file", path=str(Path(__file__))),
                  answered("looked, and wrote nothing")],
            "b": [tool_call("read_file", path=str(Path(__file__))),
                  answered("nothing was handed to me")],
        })
        runner, _records = campaign(tmp_path, plan, scripts)
        runner.run()
        told = "\n".join(t for t in scripts.seen if "Step b of a plan" in t)
        assert "expected and are NOT there" in told
        assert "figures.json" in told


# ── approval ────────────────────────────────────────────────────────────────


class TestThePlanIsApprovedBeforeAnyOfItRuns:
    """One approvals mechanism, not two.

    February's campaign had a HUMAN_REVIEW phase of its own — write the
    plan, open ``$EDITOR``, read it back — and this harness had already
    built a durable approval store with an id that outlives the process
    and ``--approval`` to carry a decision into the next run.  The durable
    one is the one that survives: an editor loop cannot be answered by a
    platform, cannot be answered tomorrow, and records nobody's name.
    """

    def unapproved(self, tmp_path, **kw):
        approvals = ApprovalStore(tmp_path / "approvals")
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts(),
                                   auto_approve=False, approvals=approvals,
                                   run_id="r-1", **kw)
        return approvals, runner, records

    def test_an_unapproved_plan_runs_no_step_at_all(self, tmp_path):
        _store, runner, records = self.unapproved(tmp_path)
        transcript = runner.run()
        assert transcript.outcome == "awaiting_approval"
        assert opened(records) == []

    def test_the_whole_plan_is_the_payload_somebody_decides_against(
            self, tmp_path):
        _store, runner, records = self.unapproved(tmp_path)
        runner.run()
        gate = events(records, GATE_REQUESTED)[0]
        assert gate["tool"] == CAMPAIGN_TOOL
        assert [s["step_id"] for s in gate["arguments"]["plan"]["steps"]] == \
            ["a", "b", "c"]

    def test_the_request_is_durable_and_carries_the_plan(self, tmp_path):
        store, runner, records = self.unapproved(tmp_path)
        runner.run()
        approval_id = events(records, GATE_REQUESTED)[0]["approval_id"]
        assert store.get(approval_id).arguments["digest"] == \
            plan_digest(fan_out())

    def test_the_stream_still_opens_and_still_closes(self, tmp_path):
        """A run that stops for a person is a run, not a silence: the
        spinner-forever state the contract's `finished` clause exists to
        prevent."""
        _store, runner, records = self.unapproved(tmp_path)
        runner.run()
        assert events(records, MISSION_STARTED)
        assert events(records, MISSION_FINISHED)[0]["outcome"] == \
            "awaiting_approval"

    def test_a_decision_carried_back_dispatches_the_plan(self, tmp_path):
        store, runner, records = self.unapproved(tmp_path)
        runner.run()
        approval_id = events(records, GATE_REQUESTED)[0]["approval_id"]
        store.decide(approval_id, approve=True, decided_by="somebody")

        again, more = campaign(tmp_path, fan_out(), fan_out_scripts(),
                               auto_approve=False, approvals=store,
                               ticket=resolve(store, approval_id),
                               run_id="r-2")
        again.run()
        assert [r["branch"] for r in opened(more)][0] == "a"

    def test_a_yes_to_one_plan_is_not_a_yes_to_another(self, tmp_path):
        """The digest and not the campaign id: an operator who edits a step
        and reruns under the same id is proposing a different campaign."""
        store, runner, records = self.unapproved(tmp_path)
        runner.run()
        approval_id = events(records, GATE_REQUESTED)[0]["approval_id"]
        store.decide(approval_id, approve=True, decided_by="somebody")

        edited = fan_out()
        edited.steps[0].description = "compute a different figure"
        again, more = campaign(tmp_path, edited, fan_out_scripts(),
                               auto_approve=False, approvals=store,
                               ticket=resolve(store, approval_id),
                               run_id="r-3")
        assert again.run().outcome == "awaiting_approval"
        assert opened(more) == []

    def test_a_refused_plan_cannot_be_carried_back_at_all(self, tmp_path):
        """`resolve` is the door, and it refuses every state that is not an
        approved unspent record — naming which one it found."""
        from core.runtime.approvals import NotApproved

        store, runner, records = self.unapproved(tmp_path)
        runner.run()
        approval_id = events(records, GATE_REQUESTED)[0]["approval_id"]
        store.decide(approval_id, approve=False, decided_by="somebody")
        with pytest.raises(NotApproved, match="refused"):
            resolve(store, approval_id)

    @staticmethod
    def editor_that(script):
        """An ``$EDITOR`` that edits, in the shape `review_plan` runs one:
        the command line, with the plan's path appended by the caller."""
        import shlex
        import sys

        return f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"

    DROP_THE_LAST_STEP = (
        "import json, sys\n"
        "p = sys.argv[1]\n"
        "d = json.load(open(p))\n"
        "d['steps'] = d['steps'][:-1]\n"
        "json.dump(d, open(p, 'w'))\n"
    )

    def test_the_plan_a_person_edited_is_the_plan_that_runs(self, tmp_path,
                                                            monkeypatch):
        """`$EDITOR` is the other way to answer the same question, and what
        somebody saves is what runs.

        The plan a review produces is a DIFFERENT plan: different steps,
        different artifacts, different scopes. Everything this runner reads
        off a plan is therefore re-derived from the edited one — the failure
        this guards is dispatching the steps somebody approved under the
        artifacts and permissions of the steps they were shown.
        """
        monkeypatch.setenv("EDITOR", self.editor_that(self.DROP_THE_LAST_STEP))
        approvals = ApprovalStore(tmp_path / "approvals")
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts(),
                                   auto_approve=False, interactive=True,
                                   approvals=approvals, run_id="r-5")
        runner.run()
        assert {r["branch"] for r in opened(records)} == {"a", "b"}
        assert [s.step_id for s in runner._plan.steps] == ["a", "b"]
        assert "c" not in runner._scopes and "c" not in runner._steps

    def test_saving_it_is_recorded_as_a_decision_with_a_name(self, tmp_path,
                                                             monkeypatch):
        """One approvals mechanism. An `$EDITOR` loop that left no record
        would be a yes nobody can audit — which is the whole reason the
        durable store is the one that survived."""
        monkeypatch.setenv("EDITOR", self.editor_that(self.DROP_THE_LAST_STEP))
        approvals = ApprovalStore(tmp_path / "approvals")
        runner, _records = campaign(tmp_path, fan_out(), fan_out_scripts(),
                                    auto_approve=False, interactive=True,
                                    approvals=approvals, run_id="r-6")
        runner.run()
        decided = [approvals.get(path.stem)
                   for path in sorted((tmp_path / "approvals").glob("ap_*"))]
        assert [a.decided_by for a in decided] == ["editor"]
        assert decided[0].tool == CAMPAIGN_TOOL

    def test_an_editor_that_saves_an_invalid_plan_decides_nothing(
            self, tmp_path, monkeypatch):
        """A plan somebody edited is a plan that can have grown a cycle.
        Every failure of the editor path is "nobody decided this", which is
        the state the durable request exists to hold."""
        monkeypatch.setenv("EDITOR", self.editor_that(
            "import json, sys\n"
            "p = sys.argv[1]\n"
            "d = json.load(open(p))\n"
            "d['steps'][0]['inputs_from'] = ['b']\n"
            "json.dump(d, open(p, 'w'))\n"))
        approvals = ApprovalStore(tmp_path / "approvals")
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts(),
                                   auto_approve=False, interactive=True,
                                   approvals=approvals, run_id="r-7")
        assert runner.run().outcome == "awaiting_approval"
        assert events(records, GATE_REQUESTED)[0]["tool"] == CAMPAIGN_TOOL
        assert opened(records) == []

    def test_no_editor_configured_falls_through_to_the_durable_request(
            self, tmp_path, monkeypatch):
        monkeypatch.delenv("EDITOR", raising=False)
        approvals = ApprovalStore(tmp_path / "approvals")
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts(),
                                   auto_approve=False, interactive=True,
                                   approvals=approvals, run_id="r-8")
        assert runner.run().outcome == "awaiting_approval"
        assert events(records, GATE_REQUESTED)

    def test_auto_approve_asks_nobody_and_writes_nothing(self, tmp_path):
        approvals = ApprovalStore(tmp_path / "approvals")
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts(),
                                   auto_approve=True, approvals=approvals,
                                   run_id="r-4")
        runner.run()
        assert events(records, GATE_REQUESTED) == []
        assert approvals.pending() == []


# ── least privilege ─────────────────────────────────────────────────────────


class TestEachStepRunsUnderItsOwnScopes:
    """``ROADMAP.md`` §5.1 invariant 10 — computed from the plan, never
    requested at run time, and the model can only narrow."""

    def readonly_plan(self):
        return CampaignPlan(
            campaign_id="readonly", objective="a reader that tries to write",
            assumptions=[],
            steps=[step("a", "read only", scopes=["fs.read"])])

    def test_a_step_that_never_asked_for_fs_write_cannot_write(self,
                                                               tmp_path):
        calls = []
        scripts = Steps({"a": [tool_call("write_file", path="/tmp/x",
                                         text="no"),
                               answered("refused")]})
        runner, records = campaign(tmp_path, self.readonly_plan(), scripts,
                                   calls=calls)
        runner.run()
        assert calls == [], "the tool ran under a step that may not write"
        result = events(records, "tool_result")[0]
        assert result["ok"] is False
        assert "fs.write" in result["output"] + result["error"]

    def test_the_same_step_may_still_do_what_it_asked_for(self, tmp_path):
        calls = []
        scripts = Steps({"a": [tool_call("read_file", path=str(
            Path(__file__))), answered("read it")]})
        runner, _records = campaign(tmp_path, self.readonly_plan(), scripts,
                                    calls=calls)
        runner.run()
        assert [name for name, _ in calls] == ["read_file"]

    def test_a_template_caps_what_a_step_may_ask_for(self, tmp_path):
        """The intersection, not the union: a step may name a scope its
        template does not permit and it does not get it."""
        capped = TaskTemplate(name="find_and_report", skill="analyst",
                              scopes=("fs.read",))
        calls = []
        scripts = Steps({"a": [tool_call("write_file", path="/tmp/x",
                                         text="no"),
                               answered("refused")]})
        plan = CampaignPlan(campaign_id="capped", objective="capped",
                            assumptions=[],
                            steps=[step("a", "wants to write")])
        plane_bus = bus(calls)
        built = six(plane_bus, [])
        built["plane"] = ToolPlane(bus=plane_bus,
                                   offered=["write_file", "read_file"])
        built["model"] = Model(ask=scripts, plain=Roles())
        runner = CampaignRunner(Run(**built), plan, workspace=tmp_path,
                                templates={capped.name: capped},
                                auto_approve=True)
        assert runner._scopes["a"] == ("fs.read",)
        runner.run()
        assert calls == []

    def test_a_template_with_no_scopes_key_caps_nothing(self, tmp_path):
        runner, _records = campaign(tmp_path, fan_out(), fan_out_scripts())
        assert runner._scopes["a"] == ("fs.read", "fs.write")

    def test_the_narrow_does_not_outlive_the_campaign(self, tmp_path):
        """A constraint set inside a step's own task dies with it, so the
        run that follows is not governed by the last step's permissions."""
        plane_bus = bus()
        runner, _records = campaign(tmp_path, fan_out(), fan_out_scripts(),
                                    plane=ToolPlane(
                                        bus=plane_bus,
                                        offered=["write_file", "read_file"]))
        runner.run()
        assert plane_bus.capability_engine.scope_constraints is None


# ── two steps at once ───────────────────────────────────────────────────────


class TestIndependentStepsMayRunTogether:

    def test_parallel_two_overlaps_the_two_independent_steps(self, tmp_path):
        """``most`` and not a stopwatch: the honest way to say two calls
        overlapped is to count the callers that were inside one at once."""
        executor = fan_out_scripts(nap=0.05)
        runner, _records = campaign(tmp_path, fan_out(), executor,
                                    parallel=2)
        runner.run()
        assert executor.most >= 2

    def test_serial_is_the_default_and_nothing_overlaps(self, tmp_path):
        executor = fan_out_scripts(nap=0.02)
        runner, _records = campaign(tmp_path, fan_out(), executor)
        runner.run()
        assert executor.most == 1

    def test_the_dependency_still_holds_under_parallel(self, tmp_path):
        runner, records = campaign(tmp_path, fan_out(),
                                   fan_out_scripts(nap=0.05), parallel=2)
        runner.run()
        order = [r["branch"] for r in opened(records)]
        assert order[0] == "a"

    def test_each_step_still_gets_its_own_artifacts_field(self, tmp_path):
        """The reason ``carry`` grew a ``branch`` keyword. The unkeyed
        queue hands whatever is pending to whichever step opens first, so
        under a wave of two one step would take both steps' artifacts and
        the other would take none."""
        runner, records = campaign(tmp_path, fan_out(),
                                   fan_out_scripts(nap=0.05), parallel=2)
        runner.run()
        by_branch = {r["branch"]: r["artifacts"]
                     for r in opened(records) if "artifacts" in r}
        assert by_branch["b"]["out"] == ["short.md"]
        assert by_branch["c"]["out"] == ["long.md"]

    def test_no_number_belongs_to_two_steps(self, tmp_path):
        runner, records = campaign(tmp_path, fan_out(),
                                   fan_out_scripts(nap=0.05), parallel=2)
        runner.run()
        owner = {}
        for record in records:
            if "index" in record and "branch" in record:
                owner.setdefault(record["index"], set()).add(record["branch"])
        assert all(len(who) == 1 for who in owner.values()), owner

    def test_steps_that_may_do_different_things_do_not_share_a_wave(self,
                                                                    tmp_path):
        """A scope allowlist is one object on one engine. Equal scopes is
        the property that makes a wave obviously safe."""
        plan = fan_out()
        plan.steps[2].capabilities_required = ["fs.read"]
        executor = Steps({
            "a": writes("figures.json", '{"total": 41}'),
            "b": reads_then_writes("figures.json", "short.md", "total 41"),
            "c": [lambda text: tool_call("read_file",
                                         path=f"{in_dir(text)}/figures.json"),
                  answered("read it")],
        }, nap=0.05)
        plan.steps[2].exports = []
        runner, _records = campaign(tmp_path, plan, executor, parallel=2)
        runner.run()
        assert executor.most == 1


# ── the synthesis ───────────────────────────────────────────────────────────


class TestTheAnswerIsWrittenOverEveryStep:

    def test_the_synthesizer_is_shown_each_steps_result(self, tmp_path):
        roles = Roles()
        runner, _records = campaign(tmp_path, fan_out(), fan_out_scripts(),
                                    roles=roles)
        transcript = runner.run()
        for name in ("figures.json", "short.md", "long.md"):
            assert name in transcript.answer, transcript.answer

    def test_the_answer_goes_out_once_as_the_campaigns_own(self, tmp_path):
        """A step's answer is a step's. The campaign's arrives whole, as
        one ``answer`` record — the same rule a staged turn follows."""
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts())
        runner.run()
        assert len(events(records, "answer")) == 1

    def test_a_finished_campaign_says_so(self, tmp_path):
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts())
        transcript = runner.run()
        assert transcript.outcome == "answered"
        assert events(records, MISSION_FINISHED)[0]["outcome"] == "answered"

    def test_the_objective_defaults_to_the_plans_own(self, tmp_path):
        """A campaign's objective is a field of the thing that was
        approved, not a sentence typed beside it."""
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts())
        runner.run()
        assert events(records, MISSION_STARTED)[0]["objective"] == \
            "measure it and write it up twice"


# ── the wire ────────────────────────────────────────────────────────────────


class TestEveryRecordConforms:

    def test_a_whole_campaign_conforms(self, tmp_path):
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts())
        runner.run()
        assert _faults(records) == []

    def test_an_unapproved_campaign_conforms(self, tmp_path):
        approvals = ApprovalStore(tmp_path / "approvals")
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts(),
                                   auto_approve=False, approvals=approvals,
                                   run_id="r-1")
        runner.run()
        assert _faults(records) == []

    def test_dropping_artifacts_leaves_the_records_a_consumer_read(self,
                                                                   tmp_path):
        """The whole reason it is an OPTIONAL field."""
        runner, records = campaign(tmp_path, fan_out(), fan_out_scripts())
        runner.run()
        without = [{k: v for k, v in r.items() if k != "artifacts"}
                   for r in records]
        assert _faults(without) == []


# ── resume ──────────────────────────────────────────────────────────────────


class _Resumption:
    """What ``--resume`` hands a campaign, in the shape it hands a swarm.

    Duck-typed for the reason ``tests/test_swarm.py`` duck-types its own:
    this file tests the campaign's half of the seam, and the door's half is
    ``tests/test_resume.py``.  It is the *same* class in production —
    :class:`~core.runtime.resume.StagedResumption` — because a campaign
    checkpoints the same ``plan`` and ``steps_done`` the swarm does.
    """

    def __init__(self, plan, steps_done=(), *, next_index=0, steps_spent=0,
                 evidence=(), called=(), replanned=False, from_seq=9):
        self.plan = list(plan)
        self.steps_done = [dict(entry) for entry in steps_done]
        self.next_index = next_index
        self.steps_spent = steps_spent
        self.evidence = list(evidence)
        self.called = list(called)
        self.replanned = replanned
        self.from_seq = from_seq

    def as_record(self):
        from core.runtime.resume import resumed_record

        return resumed_record(self.from_seq, self.steps_spent)


def state_of(plan):
    from core.runtime.campaign import _as_plan_steps

    return [step.as_state() for step in _as_plan_steps(plan)]


class TestACampaignPicksUpWhereItStopped:

    def resumed(self, tmp_path, done, **kw):
        executor = Steps({
            "b": reads_then_writes("figures.json", "short.md", "total 41"),
            "c": reads_then_writes("figures.json", "long.md", "total is 41"),
        })
        runner, records = campaign(tmp_path, fan_out(), executor, **kw)
        # `a` really ran once, in an earlier process: its export is on disk
        # where the handoff will look for it.
        out = tmp_path / "sessions" / "fanout" / "steps" / "a" / "handoff_out"
        out.mkdir(parents=True, exist_ok=True)
        (out / "figures.json").write_text('{"total": 41}')
        transcript = runner.run("", _Resumption(
            state_of(fan_out()), done, next_index=4, steps_spent=4))
        return executor, transcript, records

    A_DONE = [{"id": "a", "goal": "compute the figure", "outcome": "ok",
               "summary": "wrote figures.json"}]

    def test_the_step_that_finished_is_not_run_again(self, tmp_path):
        executor, _t, records = self.resumed(tmp_path, self.A_DONE)
        assert not any("Step a of a plan" in text for text in executor.seen)
        assert {r["branch"] for r in opened(records)} == {"b", "c"}

    def test_the_steps_that_are_left_run_with_their_artifacts(self,
                                                              tmp_path):
        _e, _t, records = self.resumed(tmp_path, self.A_DONE)
        artifacts = {r["branch"]: r["artifacts"] for r in opened(records)
                     if "artifacts" in r}
        assert artifacts["b"]["in"] == ["figures.json"]

    def test_nothing_is_announced_twice(self, tmp_path):
        """One mission, one objective, one id, one opening."""
        _e, _t, records = self.resumed(tmp_path, self.A_DONE)
        assert events(records, MISSION_STARTED) == []

    def test_no_second_approval_is_asked_for(self, tmp_path):
        """The plan on the record is the plan that was approved. Asking
        again would make a resume a place a decision could be re-litigated
        by whoever restarted the process."""
        approvals = ApprovalStore(tmp_path / "approvals")
        _e, transcript, records = self.resumed(
            tmp_path, self.A_DONE, auto_approve=False, approvals=approvals,
            run_id="r-9")
        assert events(records, GATE_REQUESTED) == []
        assert transcript.outcome != "awaiting_approval"

    def test_the_numbering_continues_the_log_it_is_appended_to(self,
                                                               tmp_path):
        _e, _t, records = self.resumed(tmp_path, self.A_DONE)
        assert min(r["index"] for r in opened(records)) == 4

    def test_the_first_new_step_says_the_run_is_being_continued(self,
                                                                tmp_path):
        _e, _t, records = self.resumed(tmp_path, self.A_DONE)
        carrying = [r for r in opened(records) if "resumed" in r]
        assert len(carrying) == 1

    def test_the_finished_steps_result_is_still_in_the_answer(self,
                                                              tmp_path):
        _e, transcript, _r = self.resumed(tmp_path, self.A_DONE)
        assert "figures.json" in transcript.answer


class TestARecordedCampaignResumesAsACampaign:
    """The CLI's rule extended: which runner continues a run is the RUN's
    fact.  A recorded campaign handed to the staged runner would re-run its
    remaining steps holding neither their artifacts nor their scopes.
    """

    def test_the_approved_plan_is_on_the_record(self, tmp_path):
        store = RunStore(tmp_path / "runs")
        run_id = store.create().run_id
        runner, _records = campaign(tmp_path, fan_out(), fan_out_scripts(),
                                    run_store=store, run_id=run_id)
        runner.run()
        assert resumed_campaign(store.meta(run_id).meta) == fan_out()

    def test_the_checkpoint_a_staged_resume_reads_is_there_too(self,
                                                               tmp_path):
        """A campaign resumes through the staged machinery, because it
        checkpoints the same two keys — so `StagedResumption` is reused
        rather than copied."""
        store = RunStore(tmp_path / "runs")
        run_id = store.create().run_id
        runner, _records = campaign(tmp_path, fan_out(), fan_out_scripts(),
                                    run_store=store, run_id=run_id)
        runner.run()
        meta = store.meta(run_id).meta
        assert [entry["id"] for entry in meta["plan"]] == ["a", "b", "c"]
        assert [entry["id"] for entry in meta["steps_done"]] == \
            ["a", "b", "c"]

    def test_a_run_that_is_not_a_campaign_reads_as_none(self):
        assert resumed_campaign({}) is None
        assert resumed_campaign({"plan": [{"id": "s1"}]}) is None

    def test_a_metadata_blob_that_will_not_parse_reads_as_none(self):
        """A resume that cannot recover the approved plan refuses rather
        than inventing one."""
        assert resumed_campaign({"campaign": {"steps": "not a list"}}) is None

    def test_the_checkpoint_is_written_before_the_first_step_runs(self,
                                                                  tmp_path):
        """A checkpoint written when the plan finishes is a checkpoint that
        never exists for the run that needed it."""
        store = RunStore(tmp_path / "runs")
        run_id = store.create().run_id
        seen = {}
        scripts = Steps({
            "a": [lambda text: seen.setdefault(
                "meta", dict(store.meta(run_id).meta)) or tool_call(
                    "write_file", path=f"{out_dir(text)}/figures.json",
                    text="{}"),
                  answered("wrote figures.json")],
        })
        plan = CampaignPlan(campaign_id="one", objective="just a",
                            assumptions=[],
                            steps=[step("a", "compute",
                                        exports=["figures.json"])])
        runner, _records = campaign(tmp_path, plan, scripts,
                                    run_store=store, run_id=run_id)
        runner.run()
        assert seen["meta"]["campaign"]["campaign_id"] == "one"


# ── the plan, on disk and by name ───────────────────────────────────────────


class TestReadingAndNamingAPlan:

    def test_json_and_yaml_are_the_same_plan(self, tmp_path):
        plan = fan_out()
        (tmp_path / "p.json").write_text(plan.model_dump_json())
        assert plan_from_file(tmp_path / "p.json") == plan

    def test_a_yaml_plan_reads_too(self, tmp_path):
        yaml = pytest.importorskip("yaml")
        plan = fan_out()
        (tmp_path / "p.yaml").write_text(
            yaml.safe_dump(json.loads(plan.model_dump_json())))
        assert plan_from_file(tmp_path / "p.yaml") == plan

    def test_the_digest_names_the_plan_and_not_its_spelling(self):
        plan, again = fan_out(), fan_out()
        assert plan_digest(plan) == plan_digest(again)

    def test_a_changed_step_is_a_changed_plan(self):
        plan = fan_out()
        edited = fan_out()
        edited.steps[0].description = "something else"
        assert plan_digest(plan) != plan_digest(edited)

    def test_the_metadata_carries_the_plan_and_its_digest(self):
        meta = campaign_meta(fan_out())
        assert meta["campaign_digest"] == plan_digest(fan_out())
        assert meta["campaign"]["campaign_id"] == "fanout"


class TestATaskTemplateIsData:
    """The middle layer of §2.6b, and the pack loader stays its one owner."""

    def test_a_packs_template_parses_into_its_shape(self):
        from core.skills import library

        pack = library.load("analyst")
        found = templates_of(pack)
        assert "find_and_report" in found
        template = found["find_and_report"]
        assert template.skill == "analyst"
        assert any(line.startswith("act — ") for line in template.shape)

    def test_a_template_with_no_skill_key_inherits_its_packs_name(self,
                                                                  tmp_path):
        (tmp_path / "t.yaml").write_text("name: t\ndescription: d\n")
        pack = type("P", (), {"name": "somepack",
                              "templates": (tmp_path / "t.yaml",)})()
        assert templates_of(pack)["t"].skill == "somepack"

    def test_a_template_that_will_not_parse_is_skipped_not_fatal(self,
                                                                 tmp_path):
        (tmp_path / "bad.yaml").write_text("::: not yaml :::\n")
        (tmp_path / "good.yaml").write_text("name: good\n")
        pack = type("P", (), {"name": "p", "templates": (
            tmp_path / "bad.yaml", tmp_path / "good.yaml")})()
        assert list(templates_of(pack)) == ["good"]

    def test_a_file_with_no_name_takes_its_own_stem(self, tmp_path):
        (tmp_path / "stem.yaml").write_text("description: d\n")
        assert load_template(tmp_path / "stem.yaml").name == "stem"

    def test_the_sentence_a_step_is_told_names_the_template(self):
        assert "'find_and_report'" in REPORTING.sentence()
        assert "act — run the computation" in REPORTING.sentence()

    def test_the_sentence_reaches_the_executors_own_instruction(self,
                                                                tmp_path):
        """Installed into the inherited rung dict rather than rendered by a
        second prompt builder, so a campaign step's prompt is composed by
        the same function a plan step's is."""
        executor = fan_out_scripts()
        runner, _records = campaign(tmp_path, fan_out(), executor)
        runner.run()
        assert any("'find_and_report'" in text for text in executor.seen)


# ── what a step is told it is ───────────────────────────────────────────────


class TestAStepRunsUnderItsPacksSkill:

    def test_a_step_whose_template_names_a_supplied_pack_opens_with_it(
            self, tmp_path):
        from core.runtime.run import Personality

        executor = fan_out_scripts()
        plane_bus = bus()
        built = six(plane_bus, [])
        built["plane"] = ToolPlane(bus=plane_bus,
                                  offered=["write_file", "read_file"])
        built["model"] = Model(ask=executor, plain=Roles())
        runner = CampaignRunner(
            Run(**built), fan_out(), workspace=tmp_path,
            templates={REPORTING.name: REPORTING},
            packs={"analyst": Personality(
                system_message="You are the analyst.")},
            auto_approve=True)
        runner.run()
        assert any("You are the analyst." in text for text in executor.seen)

    def test_a_step_whose_pack_nobody_supplied_opens_with_the_turns_own(
            self, tmp_path):
        executor = fan_out_scripts()
        runner, _records = campaign(tmp_path, fan_out(), executor)
        runner.run()
        assert any("You are Tai." in text for text in executor.seen)

    def test_the_synthesizer_always_opens_with_the_turns_own(self, tmp_path):
        from core.runtime.run import Personality

        roles = Roles()
        executor = fan_out_scripts()
        plane_bus = bus()
        built = six(plane_bus, [])
        built["plane"] = ToolPlane(bus=plane_bus,
                                  offered=["write_file", "read_file"])
        built["model"] = Model(ask=executor, plain=roles)
        CampaignRunner(
            Run(**built), fan_out(), workspace=tmp_path,
            templates={REPORTING.name: REPORTING},
            packs={"analyst": Personality(
                system_message="You are the analyst.")},
            auto_approve=True).run()
        synthesis = [t for t in roles.seen if "Step results:" in t]
        assert synthesis and "You are Tai." in synthesis[0]
