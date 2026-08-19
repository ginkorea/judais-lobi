# Integrating judais-lobi into a platform

This is the guide for the other side of the seam: you have a platform, you want
it to have an agent, and you would rather not write one.

**It is meant to be sufficient on its own.** Everything below is true of the
tree it ships with, and it is held there by a test — `tests/test_platforms_doc.py`
asserts that every event, every field, every published flag, every published
environment variable, every outcome word and every clause of the exit contract
appears on this page, and that nothing on this page claims a flag or a variable
the contract does not publish. If you find yourself opening `core/` to answer a
question about the boundary, that is a defect in this file; the sections are
numbered so it can be reported precisely.

Read it in order and you should have a platform driving a governed mission in
an afternoon. §10 is the last step and the one that keeps the other nine true:
a conformance kit you copy into your own repository, which goes red the day the
contract breaks.

> *One line of history, because the shape of this document came from
> somewhere.* This framework was deployed once before it was documented — as
> the mission agent of a governed narrative-influence platform, spawned as a
> subprocess and pointed at that platform's own tools — and nearly every
> refusal, every closed set and every "state this explicitly" below is a
> mistake that deployment made first. What is written here is the generic form
> of each. The platform's own particulars stayed in the platform's own
> repository, which is §0's whole argument.

---

## 0. What you get, and what you must provide

**One screen.** Everything after this is detail.

judais-lobi is a **CLI, a library and a contract**. It supplies mechanisms; you
supply content, and you keep that content in *your* repository, where your own
tests can hold a prompt against the code that enforces it. That is not
tidiness: a personality asserting a rule your platform does not enforce is
worse than no personality, because it tells a reader the agent is bound by
something it is not.

| you get | you provide |
| --- | --- |
| a mission loop: plan, call a tool, read the result, answer | **a personality** — who the agent is, what it may claim, what register it writes in (§4) |
| deny-by-default capability gating, an audit file, a sandbox for subprocesses | **capabilities** — tools over MCP, plus a `SKILL.md` manifest that closes the tool set and states the grounding grammar (§5) |
| a durable, resumable transcript and a replayable recording of every run | **a driver** — you spawn it, read the NDJSON stream and render it (§2, §3) |
| a grounding check that refuses an answer citing what was never retrieved | **a pin** — one git tag, deployed by name, bumped deliberately (§11) |
| a gate: a proposed call a person has to approve before it is dispatched | **a conformance test** — copied from §10, so a broken contract is a red build rather than a blank pane |
| a usage ledger, wall-clock and step ceilings, a supervisor that notices a loop | **an eval suite** — your questions about your data (§9) |

None of the six on the right is optional, and each fails *differently* when it
is skipped, which is why they are six things and not one config file:

* a missing **personality** is an agent that will not start;
* a missing **manifest** is an agent that starts holding the whole tool bus with
  no grounding check, and whose transcript looks exactly like a governed one;
* a missing **event sink** is a pane that shows a spinner;
* a missing **pin** is a host whose harness version can only be established by
  reading its code;
* a missing **conformance test** is a rename you discover from a support
  ticket;
* a missing **suite** is a change nobody measured.

---

## 1. Install

```bash
pip install 'judais-lobi[mission]'
```

**Python floor: 3.10** (`setup.py`, `python_requires=">=3.10"`). Two
consequences: `tomllib` is 3.11+, so on 3.10 a TOML personality needs `tomli`
(a declared requirement, not an extra — the loader tries `tomllib`, then
`tomli`, then refuses with that sentence); and every optional stack is an
extra, so a plain install stays small enough that `judais --help` works with
none of them.

### The extras

| extra | what it installs | install it when |
| --- | --- | --- |
| `mission` | `mcp`, `pyyaml`, `jsonschema` | **always, to run a mission.** This is the one a platform installs |
| `mcp` | `mcp` alone | you want the tool bridge and nothing else. See the trap below |
| `critic` | the Anthropic and Google SDKs, `keyring`, `pyyaml` | you switch `critic: true` on in a manifest's `grounding:` block and want a hosted second opinion |
| `anthropic` | the Anthropic SDK | `--provider anthropic`. Soft-imported, so `judais --help` works without it |
| `server` | the SSE endpoint's dependencies | you want to follow a run over HTTP instead of a pipe. **0.16** |
| `treesitter` | tree-sitter and seven grammars | the repo map should parse C, C++, Rust, Go, JavaScript, TypeScript or Java rather than fall back |
| `faiss` | `faiss-cpu` | the long-term memory is big enough for the vector index to matter. The numpy inner-product fallback is always there |
| `voice` | TTS, torch, audio | you want the agent to speak |
| `dev` | `pytest`, `pytest-cov` | you are running the suite |

> **The `[mcp]` trap.** `pip install 'judais-lobi[mcp]'` gives you a *runnable*
> mission and a *silently ungoverned* one: `--skill` reads YAML frontmatter,
> and with no `pyyaml` the manifest never loads, so the closed tool set and the
> grounding check are simply absent while the transcript looks identical.
> Install `[mission]`.

### bubblewrap, and what changes without it

`bwrap` is **optional**. Wherever bubblewrap is on `PATH`, tool *subprocesses*
run inside it; where it is not, they do not, and the difference is stated on
the wire: `mission_started.sandbox` is `"bwrap"` or `"none"`. `--unsandboxed`
(or `JUDAIS_LOBI_SANDBOX`) opts out explicitly.

**`sandbox` describes the subprocess plane only.** A bridged MCP tool is
dispatched *in this process* — an HTTP or stdio call out of the harness — and
touches no sandbox whatever this field says. So `sandbox: "none"` is not a
finding for an MCP-only agent, and a platform whose whole tool plane is MCP can
run without bubblewrap and lose nothing. The moment the closed tool set
contains a **code-plane** tool — a shell, an interpreter, a `pip install` — the
manifest must declare `sandbox: bwrap` *and* the run must actually get it, or
the resolve refuses at the door (§5). Those are the two different situations,
and only the second needs bubblewrap on the host.

---

## 2. Three ways to run it

### 2.1 A subprocess and an NDJSON stream — the one to start with

```
judais --mission                        \
       --mcp-url  https://host/mcp      \
       "<the objective>"                \
       --mission-steps 24               \
       --mission-seconds 900            \
       --provider local                 \
       --model    org/model-name        \
       --skill    /path/to/skills/thing \
       --events   fd:7                  \
       --control  fd:8                  \
       --history  /tmp/turn-history.json \
       [--gate-tool mcp.some_tool]…     \
       [--approval ap_<id>]             \
       [--protocol native]              \
       [--swarm]
```

with `MCP_TOKEN`, `MCP_CLIENT_NAME`, `ELF_PERSONALITY`, `LOCAL_API_BASE` and
`LOCAL_MODEL` in the environment. The objective is a positional argument. A
resumed turn is the same line with `--resume <run-id>` and **no objective**:
the recorded run holds it, and passing a different one is refused.

**Two channels, and only one of them is yours.**

**stdout is prose for a person** — panels, emoji, the transcript printed after
the fact. It is not a machine channel and a consumer must not parse it. It
changes whenever somebody improves the console rendering, which is as often as
somebody improves the console rendering.

**The event sink is the only machine channel.** `--events` takes three forms:

| form | goes to | for |
| --- | --- | --- |
| `-` | stdout | a person with `jq` |
| `fd:N` | an inherited descriptor | **a harness** |
| *path* | a file, opened for append | a reader that arrives late |

A consumer uses `fd:` or a path, never `-`, so the rendering and the records
never share bytes. `fd:N` is what a driver wants: open a pipe, pass the write
end through `pass_fds`, and each line arrives the moment it happens with no
file to tail.

`--control` is the channel *into* a run and is §7.

### 2.2 The library — `from judais_lobi import Run` &nbsp;·&nbsp; **0.16**

The same contract the CLI speaks, without a subprocess. The CLI becomes a
client of it: `_mission` in `core/cli.py` is argparse building these objects.

**Six objects and a loop**, which is the whole API:

```python
from judais_lobi import (Bounds, Model, Observer, Personality, Run, Store,
                         ToolPlane, Tools)

bus = Tools(root=".").bus                        # SAFE, sandboxed, audited
run = Run(Personality(system_message="You are the agent."),
          ToolPlane(bus=bus, offered=["read_file"]),
          Bounds(), Store(), Observer(), Model(ask=my_chat_fn))
print(run.run("what does this repository build?").answer)
```

**`root=` confines the in-process tools**, and a platform building a plane by
hand has to decide it. bwrap isolates a *subprocess*; `fs` and `patch` are
`pathlib` in the interpreter that asked, so an unrooted bus under a profile
granting `fs.write` writes anywhere the user can. `Tools(root=path)` gives
`fs`, `patch`, `git` and `repo_map` one directory tree and refuses anything
resolving outside it — absolute, `..`, or through a symlink — as an ordinary
tool result, exit code 1, on the stream where the model reads it. The CLI
passes the working directory for `--mission` and nothing for a chat turn
(`core/cli.py::_build_agent`); `core/tools/root.py` owns what "inside" means.
There is no flag and no environment variable: the root IS the directory the
mission runs in, and a mission that needs another one is run from there.

`my_chat_fn` is `messages -> str` and nothing else: the loop is confined to one
injected callable and cannot ask a backend anything the caller did not offer.
**Almost every other default means *nothing*** — no bus of its own, no ceiling,
no clock, no durable log — so a platform adds the ones it wants and
pays for nothing else. `Skill` and `load_skill` read a `SKILL.md` (§5);
`Deadline` and `Cancellation` build a real `Bounds` (§7); `RunStore` is the
`Store` (§6); `MissionWindow` is the `Model`'s context bound.

The exception — the one default that is not *nothing* — is the **supervisor**.
`Bounds()` carries one: `Run` builds it from the model the run was given, and
every child of the run shares it, so a turn has one review budget the way it
has one clock. A run that is getting somewhere pays nothing for it (no signal
fires, no call is made), and it is the only thing that ends an endless loop now
that there is no step budget — so leaving it unset would have made the example
above fail open on the single bound 1.0 has. A platform that wants a run
nothing but a clock or a person can stop says so out loud:
`Bounds(supervisor=NO_SUPERVISOR)`. Passing your own `Supervisor(...)` (§7)
still wins over both.

The `Observer` is handed the **same records** that go on the `--events` stream,
so everything in §3 applies unchanged and a platform can move between the
subprocess and the library without touching its renderer. `contract` is
re-exported from the façade too, so a consumer can call `conforms()` without
knowing which of the two produced the stream.

> **0.16.** The façade ships as a single top-level module, `judais_lobi.py`, so
> the wheel's top-level names stay `core`, `judais`, `lobi` — which
> `tests/test_packaging.py` pins. Until then, `core.runtime.mission.MissionRunner`,
> `core.runtime.swarm.SwarmRunner` and `core.runtime.campaign.CampaignRunner`
> are the objects, and none of the three is a stable surface: the façade
> exports the six and what builds them, and a runner over them is reached by
> its module path.

**The coding kernel, for a platform that wants the other half.** A mission is
one loop; the kernel is the multi-phase coding path, and a library caller drives
it through its own objects. Six lines, and the dispatcher is bounded against the
endpoint's real context window without being asked:

```python
from core.agent import Agent
from core.kernel import Orchestrator
from core.kernel.workflows import get_coding_workflow

agent = Agent(config=my_personality)            # your PersonalityConfig
workflow = get_coding_workflow()
state = Orchestrator(dispatcher=agent._make_task_dispatcher(workflow=workflow),
                     tool_bus=agent.tools.bus, workflow=workflow).run("add pagination")
```

`state` is the final `SessionState` — `COMPLETED` or `HALTED`, the halt naming
the phase that stopped it. Pass `budget=BudgetConfig(...)` to both (the same
object, so the dispatcher's per-phase and the orchestrator's per-session budgets
agree), and `session_manager=` to `Orchestrator` for durable artifacts. The
single-task entry point `Agent.run_task` was **removed** in Phase 11 — nothing
in the package or its CLI called it — so `0.16` is the first release without
it, and `Agent.run_campaign`, `Agent.run_campaign_from_description` and
`Agent.draft_campaign_plan` went the same way in 0.17: they were the door onto
a *second* dispatcher, and a campaign is a `Run` client now. See
**Campaigns — a plan of missions**, below.

### 2.2b Campaigns — a plan of missions &nbsp;·&nbsp; **0.17**

A campaign is a DAG of missions with artifact handoff, human approval and a
resume. From the command line it is `--campaign-plan ./mission.json` (or
`--campaign "<description>"`, which drafts one); as a library it is one more
object over the same `Run` a mission is:

```python
from core.runtime.campaign import CampaignRunner, plan_from_file, templates_of
from core.skills import library
from judais_lobi import Run                      # plus the six, as in 2.2

pack = library.load("analyst")
runner = CampaignRunner(
    Run(personality, plane, bounds, store, observer, model),
    plan_from_file("mission.json"),
    templates=templates_of(pack),                # the menu a step may name
    packs={"analyst": personality},              # what a step is told it is
    parallel=2,                                  # independent steps together
    auto_approve=False,                          # ask, through the store
)
transcript = runner.run()
```

Four things a driver has to know about one:

* **It stops for approval.** With no ticket the run ends at
  `awaiting_approval` having dispatched nothing, with the whole plan on a
  `gate_requested` record whose `tool` is `campaign_plan` and whose
  `arguments` carry the plan and its digest. That is the **same** mechanism a
  gated tool call uses — the same store, the same `approval_id`, the same
  `--approve <id>` / `--approval <id>` round trip (§5, *Gates and approvals*) —
  so a platform that already answers gates answers campaign plans with no new
  code. The digest is compared on the way back in, so a yes to one plan is not
  a yes to the plan that replaced it.
* **Each step is a child run.** Every record carries `branch` — the step's id —
  exactly as a `--swarm` stage's does; the plan rides the first `step_started`
  as `plan` (with `rung` naming each step's task template) and each step's own
  `step_started` carries `artifacts`: `{"in": [...], "out": [...]}`. Nothing
  required was added and `SCHEMA_VERSION` is still `1`.
* **Files, not summaries, travel between steps.** A step's declared inputs are
  copied into `sessions/<campaign>/steps/<step>/handoff_in/` before it starts
  and its declared exports are collected from `handoff_out/` after. A step that
  promised a file and did not write it **failed**.
* **`--resume` continues it as a campaign.** The approved plan is in the run's
  metadata, so the runner that picks a recorded run back up is chosen off the
  *record* and not off the resuming command line — the same rule `--protocol`
  and the objective are read under.

### 2.3 Server-sent events over the run store &nbsp;·&nbsp; **0.16**

The `[server]` extra serves a run's stream over HTTP by following `RunStore`
(§6) rather than by holding a subprocess, so it is a *store* client: a pane can
attach to a run it did not start, and reattach to one it lost. `python -m
core.server` (`--runs DIR`, or `JUDAIS_LOBI_RUNS`) serves `GET /healthz`,
`GET /runs`, `GET /runs/{run_id}`, `GET /runs/{run_id}/events?since=` (SSE:
`event:` = the record's event, `id:` = its seq, `data:` = the record; replays
from `since` then follows to `mission_finished`; `Last-Event-ID` reconnects)
and `GET /runs/{run_id}/agui?since=` (the same, through the one AG-UI
translator). It is read-only: the subprocess-and-NDJSON seam remains the one
for a platform that owns the process and wants to steer it. What a platform
needs to know beyond the routes is the three operational rules they were built
around,
because each is a production incident somebody already paid for:

* **the stream cap sits below the connection ceiling**, so a run is closed by
  the thing that knows it is a run rather than by a proxy that thinks it is an
  idle socket;
* **the heartbeat interval sits inside the socket write timeout**, or an
  idle-but-healthy run is reaped as dead;
* **nothing is refused after the first byte** — a stream that has begun does
  not turn into an error page, because a client that has started rendering has
  no way back.

---

## 3. The contract, in one table

The record vocabulary is **eleven event types**, and its authority is
`core/runtime/contract.py` — `SCHEMA_VERSION`, `EVENTS`, `FIELDS`, `OPTIONAL`,
`OUTCOMES`, `CLI_FLAGS`, `ENV_VARS`, `EXIT_CONTRACT` and `conforms`, all of it
data rather than prose. `CONTRACT.md` is the long human rendering. This table
is the short one, and a test holds it against the module in both directions.

Every record carries `event`. One optional field is universal — **`branch`**
(0.16): present on a record a *child* run emitted (a `--swarm` plan step, a
campaign step, the direct route) and absent on the records the turn emitted
itself, which on a `--swarm` turn is the opening frame; its value is `"direct"`
or the step's id. **`direct` is the mission's own answer routed direct**, not a
stage of anything: on the unplanned route the turn's `answer`, `grounding` and
`mission_finished` carry it, and a consumer that groups by `branch` must read
that group as the turn. A consumer that never heard of the field reads one
correctly-ordered sequence — the stream it always read; a consumer that wants
to demultiplex children groups by it. It is not listed per row below because
what it says is not about the record's kind.

| event | required fields | optional fields |
| --- | --- | --- |
| `mission_started` | `schema_version`, `objective`, `catalogue`, `gated`, `max_steps`, `history` | `sandbox`, `profile`, `audit_ref`, `run_id`, `protocol`, `branch` |
| `step_started` | `index` | `plan`, `compacted`, `resumed`, `injected`, `catalogue`, `review`, `branch` |
| `reply_rejected` | `index`, `problem` | `tool`, `usage`, `branch` |
| `tool_call` | `index`, `tool`, `arguments` | `usage`, `call`, `branch` |
| `tool_result` | `index`, `tool`, `arguments`, `ok`, `exit_code`, `output`, `error`, `handle`, `truncated` | `call`, `branch` |
| `gate_requested` | `index`, `tool`, `arguments`, `reason` | `approval_id`, `branch` |
| `answer_delta` | `index`, `part`, `text` | `branch` |
| `answer` | `text`, `outcome` | `usage`, `branch` |
| `grounding` | `ran`, `grounded`, `verified`, `repairs`, `repairing`, `caveat`, `unsupported`, `silent`, `uncited`, `checks` | `branch` |
| `mission_finished` | `outcome`, `steps`, `max_steps` | `usage`, `budget`, `reason`, `elapsed_s`, `branch` |
| `model_state` | `state`, `provider`, `model` | `index`, `detail`, `since_s`, `retry_after_s`, `branch` |

**`model_state`** (0.16, the eleventh) says why a pane is waiting: `state` is
one of `cold`, `asking`, `queued`, `loading`, `loaded`, `failed`, `absent`
(`contract.MODEL_STATES`), with `detail` (the server's sentence), `since_s`
(how long the run has been in it) and `retry_after_s` (a `Retry-After` the
server sent). **A healthy call emits none of them** — the record's presence is
the signal — and `loaded` closes a wait. `queued` and `loading` are separated
by construction: `loading` is only ever the server's own 503; `queued` is a
429 or an accepted request with no first byte while `/models` lists the model.
Branch on `state`, render `detail` as prose, hold the last state until
`loaded`; never treat it as an error — a model that is loading is a run that
has not failed.

**Read every optional field with a default, and never read an absent one as a
zero.** Absence and a stated null are different facts throughout: an absent
`usage` is a provider that reported nothing (which local endpoints routinely
do), a null `audit_ref` is auditing switched off, an absent `run_id` is nothing
being recorded, and an absent `protocol` is a `json` run.

### The five outcome words

`mission_finished.outcome` says exactly one of these five. `answer.outcome`
carries the same word, and can only ever be one of the first two — an answer
that exists is an answer:

| outcome | what a driver does |
| --- | --- |
| `answered` | render it |
| `answered_with_caveat` | render it, and show the caveat — the grounding check could not support part of it |
| `awaiting_approval` | a gate was requested and nobody answered it in this run; §5 |
| `budget_exhausted` | a ceiling ran out. `mission_finished.budget` is present exactly here |
| `incomplete` | it stopped. With a `reason` it is somebody's decision (`"cancelled"`, `"stuck"`); with **no** reason it is a crash, and stderr's tail is what to show |

**Stopping is not an outcome word**, and `reason: "stuck"` is not a failure —
the supervisor asks for a best answer, which usually earns `answered` (§7).

### The opening frame is the run's posture

`mission_started` is the one record to read in full before rendering anything.
Its six optional fields say what kind of run this is:

| field | what a driver does with it |
| --- | --- |
| `sandbox` | `"bwrap"` or `"none"` — the isolation the tool **subprocesses** ran under. Show it: a pane that cannot say whether a shell ran isolated cannot answer the only question an operator will ask |
| `profile` | `safe` \| `dev` \| `ops` \| `god` — the capability profile. A `safe` mission and a `god` one are otherwise indistinguishable on the wire |
| `audit_ref` | the path of this process's append-only audit file, or **`null`** when `JUDAIS_LOBI_AUDIT` was `none`/`off` |
| `run_id` | the durable transcript (§6). **Absent**, not null, when nothing is being recorded |
| `protocol` | `"native"`, and **absent** on a `json` run — which keeps every stream recorded before the field existed byte-identical |
| `granted` | the scopes `--grant` pre-authorised **beyond** `profile`, sorted, and **absent** on every run nobody widened. Read it beside `profile`: since 0.17 the profile is the floor a deployment set and this is what the operator typed on top of it, so a pane that renders only `profile` is now under-reporting what a run may do |

### The published spawning surface

`contract.CLI_FLAGS` is the closed set of mission flags a consumer may rely on.
Everything else in `judais --help` is a *person's* surface and may move between
releases.

| flag | env | what it does |
| --- | --- | --- |
| `--mission` | — | mission mode. Without it none of the rest applies |
| `--events` | `MISSION_EVENTS` | the record sink: `-`, `fd:N`, or a path |
| `--control` | `MISSION_CONTROL` | the channel *into* the run (§7) |
| `--mcp-url` | `MCP_URL` | an HTTP MCP endpoint. Repeatable and namespaced |
| `--mcp-stdio` | `MCP_STDIO` | an MCP server to spawn over stdio. Repeatable and namespaced |
| `--mcp-token` | `MCP_TOKEN` | the bearer token, paired with the `--mcp-url` in the same position. **Use the variable**: argv is world-readable |
| `--mcp-timeout` | `MCP_TIMEOUT_S` | per-call timeout for MCP tool calls, in seconds, for every server on the plane. A property of the platform holding the other end, like `--gate-wait`: a broker that stages a large bundle before returning its handle legitimately takes longer than the default 30. Non-positive means the default; zero is not a value |
| `--skill` | `MISSION_SKILL` | the manifest directory or file, or the NAME of a shipped pack — `research`, `coding`, `analyst` (§5) |
| `--swarm` | `MISSION_SWARM` | plan the mission as steps rather than one loop |
| `--protocol` | `MISSION_PROTOCOL` | `json` (default) or `native` tool calling |
| `--no-stream` | `MISSION_STREAM` | suppress `answer_delta` |
| `--mission-steps` | — | an operator's step ceiling. **Unset means none** |
| `--mission-seconds` | `MISSION_SECONDS` | an operator's wall clock. **Unset means none** |
| `--gate-tool` | — | a tool this deployment offers and gates; repeatable (§5) |
| `--gate-wait` | `MISSION_GATE_WAIT` | how long a gate waits for a decision on `--control` |
| `--approval` | `MISSION_APPROVAL` | spend one approved gate record on this run (§5) |
| `--resume` | `MISSION_RESUME` | continue an unfinished run against a live model (§6) |
| `--replay` | `MISSION_REPLAY` | run a finished recording again, dialling nothing (§6) |
| `--history` | `MISSION_HISTORY` | a JSON file of prior chat turns |
| `--provider` | — | `openai` \| `anthropic` \| `mistral` \| `local` (§8) |
| `--model` | — | the model name, as the provider serves it |
| `--profile` | `JUDAIS_LOBI_PROFILE` | `safe` \| `dev` \| `ops` \| `god` |
| `--grant` | — | pre-authorise named scopes for this run, past the profile. Comma-separated, repeatable. Scopes only: the sandbox, the gated set and the manifest's closed set are unchanged. Arrives back as `granted` (§5) |
| `--campaign` | — | run a plan of missions drafted from the message (§5) |
| `--campaign-plan` | — | run a plan of missions from a `CampaignPlan` JSON/YAML file. Both imply `--mission` |
| `--unsandboxed` | `JUDAIS_LOBI_SANDBOX` | run tool subprocesses with no isolation |
| `--temperature`, `--top-p`, `--seed` | — | sampling, passed through to the backend |

The rest of `contract.ENV_VARS`, which have no flag:

| variable | what it does |
| --- | --- |
| `MCP_CLIENT_NAME` | **what this client calls itself in the `initialize` handshake** — see §5, and set it |
| `ELF_PERSONALITY` / `TAI_PERSONALITY` | where the personality file is (§4) |
| `LOCAL_API_BASE` / `LOCAL_MODEL` | the OpenAI-compatible endpoint on this host, and the name it serves (§8) |
| `JUDAIS_LOBI_AUDIT` | move the audit file (a path) or silence it (`none`/`off`) |
| `JUDAIS_LOBI_RUNS` | move the run store (a path) or keep nothing (`none`/`off`) |
| `JUDAIS_LOBI_APPROVALS` | move the approvals directory |
| `JUDAIS_LOBI_MEMORY` | a directory you own: switches memory ON (0.16). Core blocks in the system turn, `memory_recall`/`memory_write` on the plane, notes written by reflection. Unset = no memory, not a byte differs |
| `JUDAIS_LOBI_MEMORY_PRINCIPAL` | the person or tenant the mission runs for. **Attributed, not authenticated** — core has no principal system and will not invent one; it partitions the bank and nothing more; a platform that needs isolation gives each tenant its own directory |

### The exit contract

Seven clauses, all of them promises about the *process* rather than about any
record. They are `contract.EXIT_CONTRACT`, and a platform builds behaviour on
them:

* **`stdout`** — prose for a person. Not a machine channel. Do not parse it.
* **`events`** — the only machine channel, and the three forms above.
* **`control`** — the only channel *in*. Nothing on it is an event: the run
  answers a command by doing the thing, and `step_started.injected` is the only
  trace on the stream.
* **`silence`** — **a mission that emits zero events has failed.**
  `mission_started` goes out before the model is asked and before the tool
  plane is touched, so an empty stream is a harness that never got that far: a
  cold model server, a refused token, an unreachable endpoint. It is never an
  empty answer. Report it as a failure rather than rendering a blank reply.
* **`finished`** — **`mission_finished` always arrives.** It comes out of a
  `finally`, so a mission killed by an exception still closes its own stream. A
  stream that simply stops is indistinguishable from an agent that is thinking,
  and a pane spinning forever is the state an operator cannot leave.
* **`sigterm`** — **SIGTERM asks a run to wind up, and it gets to.** The first
  signal throws the mission's cancellation: the loop stops at its next step,
  keeps its transcript, writes its own `mission_finished` (`incomplete` with
  `reason: "cancelled"`), and only then is the sink flushed and closed. The
  default disposition is restored and the signal re-raised, so the exit status
  is still the signal's. A **second** SIGTERM does not wait.
* **`diagnostic`** — **stderr carries the diagnostic**, and its tail is what to
  show when a mission produced no events or stopped without an answer. It is a
  traceback, and it is **scrubbed before it is written**: home directories, the
  host's name, credentials held in the process's environment and absolute frame
  paths become `<home>`, `<host>`, `<cwd>`, `<site-packages>`, `<stdlib>` and
  `<redacted:NAME>`, by the same `core.redact` pass every free-text field on the
  stream goes through. A platform may show it to somebody who is not an
  operator and needs no location sweep of its own. `tool_result.output` and
  `arguments` are deliberately left alone: they are the evidence and the call.

**Process exit status**, which is the part of "it is over" that is not a
record: `0` when the mission ran, whatever its outcome — an `incomplete` run is
a completed process; `2` for a refusal at the door (an unparseable flag, a
personality that could not be found), which prints one sentence and no
traceback; `1` for anything unhandled, which prints the scrubbed traceback
above; and the signal's own status when a run was signalled. **Branch on the
outcome, never on the status**: a mission that answered and a mission that was
cancelled both exit `0`, and that is deliberate.

### Streamed answers — render them, then replace them

Streaming is on by default wherever the backend declares it. Fragments arrive
as `answer_delta` records — `index`, `part` (0-based, restarting at 0 for every
model call) and `text`.

The rule for a pane is one sentence: **render the fragments as they land and
replace the lot with `answer.text` when the `answer` record arrives.** That
record is always emitted, never suppressed because the deltas added up to the
same string, and only it has been through the grounding path that may append a
caveat. Key provisional text by `index` and clear it on the next
`step_started`: a turn whose reply was rejected leaves fragments behind that no
`answer` will replace. Fragments are scrubbed per fragment, so a credential
split across two of them is not recognisable in either half.

**Zero of them is normal** and needs no special case — `--no-stream`,
`MISSION_STREAM=off`, a backend that does not stream, or a turn that called a
tool instead of answering.

### `--protocol native`, and the one thing that changes on the wire

Default is `json`. Under `--protocol native` the request declares the mission's
tools as functions plus a synthetic `mission_answer(text)` and asks for
`tool_choice=required`, so an unparseable reply and a tool name nobody offers
become unrepresentable rather than caught a turn later. It is refused at the
door on a backend that declares neither tool calls nor required tool choice.

Exactly one thing changes, and a driver that does not handle it renders a turn
wrong: **one model turn may produce several `tool_call`/`tool_result` pairs
under one `index`**, told apart by the `call` ordinal — absent on the first
call and absent for every call of a `json` run. `index` still numbers the
*model turn*. A call the harness refused before dispatching it still uses up
its ordinal, so a gap in `call` is a refusal and not a lost record, and `usage`
rides the **first** record of a turn only. A gated tool ends the turn on that
call: the calls before it have run, the ones after it are not dispatched, and
`gate_requested.reason` says how many.

Arguments are checked against each tool's own JSON Schema before dispatch in
**both** protocols (`jsonschema` when `[mission]` is installed, a
`required`/`type`/`enum` floor when it is not). A violation is a
`reply_rejected` naming the tool, the field and the rule.

### `--history` — prior turns, as turns

A JSON file: an array of `{"role": "user"|"assistant", "content": "…"}`, oldest
first. `system` is refused — system text belongs to the harness — and so are
tool turns, which are this mission's own to make. Caps: 100 turns, 262 144
characters. A malformed history is a refusal at the door, never a silent drop,
because a dropped history is the bug this flag fixes wearing a different hat.

A file rather than an argument, for the same reason `--mcp-token` prefers the
environment: a conversation is many kilobytes and argv is world-readable.

**A caller passing `--history` must not also fold the history into the
objective.** The turns are seeded as *real role-tagged chat messages* ahead of
the objective. A chat-tuned model attends to those and skims past the same text
pasted into the message: measured 12 August 2026, "tell me more about #2"
web-searched `#2` literally while the list sat two lines up in the prompt.

### Metering

`mission_finished` carries an optional `usage` —
`{prompt_tokens, completion_tokens, total_tokens, calls}` — and the three
records that follow a model call (`tool_call`, `answer`, `reply_rejected`)
carry that one call's. It is **what the provider said**, never an estimate, and
it is **absent rather than zero** when the provider said nothing. A platform
that bills from it must read it with a default and must not read a missing
field as free.

Cost is the platform's to configure, because the framework cannot know it. A
`pricing:` block in the project's `.judais-lobi.yml` adds
`cost: {amount, currency}` inside the `mission_finished` ledger:

```yaml
pricing:
  openai:
    gpt-4o-mini: {prompt_per_1k: 0.15, completion_per_1k: 0.6}
  local:
    my-served-model: {prompt_per_1k: 0.002, completion_per_1k: 0.002, currency: EUR}
```

Keys are the provider — any of the four — and the model name as it was asked
for, with `"*"` under a provider covering whatever else it serves. No block is
the normal case: the ledger then carries tokens and no `cost` key at all. This
repo ships no price list and never will: prices move, they differ per account,
and a wrong number is worse than none because somebody bills from it.

### AG-UI, if your frontend speaks it

`core/runtime/agui.py` turns these records into AG-UI event frames. It is
optional and import-free — dicts only, no AG-UI SDK, and nothing in this repo
imports it. Two entry points:

```python
from core.runtime.agui import Translator, translate

# a whole run, or a replay out of RunStore.since(0): pure, deterministic
for frame in translate(records, thread_id=thread, run_id=run):
    send(frame)

# a live follower: feed() as each line arrives, close() at EOF
t = Translator(thread_id=thread, run_id=run)
for record in stream:
    for frame in t.feed(record):
        send(frame)
for frame in t.close():          # closes what is open; RUN_ERROR if the
    send(frame)                  # harness died without `mission_finished`
```

It takes wire records **or** `{seq, at, record}` store envelopes, so a replay
and a live pane are one code path. Three behaviours are the point of the module
rather than incidental to it, and a platform writing its own translator should
copy them:

* **A rejected reply is mechanics, not content.** The loop's correction prompt
  rendered as prose reads as the agent saying something incoherent. It goes out
  marked, never as a text message.
* **The grounding verdict rides the answer's own frames**, so a renderer badges
  the answer rather than drawing a sibling a reconnect can separate from it. An
  interim `repairing: true` report does not close the message.
* **One answer, several bounded frames**, whether the harness sent deltas or
  not, so the incremental path is exercised on every run.

`incomplete` with **no** reason becomes `RUN_ERROR` (it is a crash);
`incomplete` **with** a reason becomes `RUN_FINISHED`, because rendering a
person's own decision as a failure tells them something went wrong with the
thing they asked for.

---

## 4. The personality

### The file

A personality is a `PersonalityConfig` written down. `PersonalityConfig.from_file`
is a **loader and not a second schema**: the keys are exactly that model's
fields, and an unknown key is refused by name at load time rather than
absorbed. A typo'd `system_message` that silently produced an empty system
message would be discovered by reading the agent's output, which is the worst
possible place to discover it.

Suffixes: `.toml`, `.json`, `.yaml`, `.yml` — closed, and an unknown suffix is
refused rather than parsed hopefully. YAML needs `pyyaml`; TOML on 3.10 needs
`tomli`.

| field | required | default | what it is |
| --- | --- | --- | --- |
| `name` | **yes** | — | what the agent is called in its banner, its answer header, and every refusal |
| `system_message` | **yes** | — | the prompt. Everything the agent *is* |
| `examples` | no | `[]` | few-shot `(user, assistant)` pairs. Omit them and you get **none** — never a set borrowed from another personality |
| `text_color` | no | `cyan` | the console style |
| `env_path` | no | `~/.elf_env` | execution-environment directory; API keys load from its `.elf_env` file. A direct dotenv-file path also works |
| `rag_enhancement_style` | no | `""` | how retrieved material is to be used in an answer |
| `default_provider` | no | `None` | the backend when no `--provider` is passed |
| `default_model` | no | `None` | the model when no `--model` is passed |

`--personality` swaps the config and nothing else: the same `Agent` class, the
same memory, the same tools. JudAIs and Lobi stay compiled-in Python and are
untouched by any of this.

### How a platform points at one

Three ways, consulted in this order:

1. **`$TAI_PERSONALITY`** — a path. Must exist, or it is not consulted further.
2. **`$ELF_PERSONALITY`** — the same, under the older name. Both are live, and
   `--personality` itself defaults to `$ELF_PERSONALITY` for every agent, so
   this is the one variable that works for `lobi`, `judais` and the mission
   agent alike. **This is the route to take**: export it into the subprocess
   you spawn, pointing at a file your own package ships.
3. **An installed package resource** — `<your package>.agent.personalities/<name>.toml`,
   via `importlib.resources`. A **guarded** import: a deployment package that
   is simply not present is an ordinary `None` and not an error, because this
   framework is installable and runnable on its own. Route 3 is for a platform
   installed *beside* the framework in one environment, where the file that
   matches the running code is the one shipped with it.

An explicit `--personality` on the command line beats all three.

**There is no fourth step, and no guess.** The resolver used to search fixed
directories under `$HOME` and a sibling of the cwd, with another repository's
source layout frozen into a constant — one developer's laptop, installed onto
every other machine. A guess that lands on the *wrong* checkout is worse than
no guess: it starts an agent whose stated governance rules are not the rules it
loaded, and the banner says the right name either way. So the third outcome is
a **refusal** naming exactly what was consulted, which variable was unset and
which pointed at nothing (different repairs), and how to point either at a
file. Exit status 2.

### Giving a personality a name of its own

A personality reachable only by asking for a *different* agent does not have a
name. The mission personality shipped for weeks as a TOML file plus
`--personality`, which made it loadable — but the only way to run it was to
ask for another agent, so its banner said the other agent's name and nobody
reading `main.py` would learn it existed.

Three edits give one a name, and a platform does **not** have to make them —
spawning `judais` with `ELF_PERSONALITY` exported is enough:

1. **An entry function in `core/cli.py`.** `main_tai` is the pattern: no
   arguments, reads `sys.argv` itself, resolves the personality file, appends
   `--personality <path>` if the caller did not, and calls `_main`. For a
   personality your platform *ships*, it is shorter — resolve the resource and
   hand it over.
2. **A row in `main.py`'s `AGENTS` table**, `{"name": (main_fn, "one line for
   --help")}`. The dispatcher's `--help` is generated from it, so a name absent
   from the table is a name nobody discovers.
3. **A console entry point in `setup.py`**, beside the ones already there.

### What does not belong in a personality

A personality states **what is true of this deployment and this agent's
standing**. It must not state **what happened on this turn**, and it must not
state anything the platform does not actually enforce.

* **Deployment facts belong here.** "The model that drives a mission is local"
  is a property of an arrangement, it costs money and latency to give up, and a
  prompt is the right place to say it. Same for the governance rules the agent
  is bound by — each one enforced somewhere in the platform's repository, with
  a test *there* holding the prompt's text against the enforcement.
* **Turn facts belong in a grounding check.** "I used the SDK" is a claim about
  which plane was called *this turn*, and a prompt cannot check it. Asked to
  "use the SDK" on a pane granting no code plane, an agent wrote "Using the SDK
  I accessed…" while calling only MCP tools — contradicting the sidebar on the
  same page. The real fix is a check keyed on the tool set actually offered:
  the `planes:` block in §5.
* **Absolute claims rot.** A line asserting that no mission prompt ever reached
  a service off the machine was true when written and stopped being true when
  web search was added. The repair was to delete it rather than soften it — and
  not even to restate it as a quotation, because a test that greps the file by
  substring cannot tell a historical quotation from a reinstated rule.
* **Anything the framework already knows.** Tool names, the catalogue, the
  shape of a result. Those come from `tools/list` and the manifest, once; a
  second copy in the prompt disagrees with the first the day a server changes a
  description.
* **How to work a governed plane.** Since 0.17 that is the framework's, not
  yours — see below.

### The conduct: what you no longer have to write

Every deployment of this framework wrote the same paragraph for itself, and it
is now a module constant that every run carries:
`core/runtime/prompts.py`, `GOVERNED_PLANE`, stacked into the system turn
between the catalogue and core memory — after the list of tools it governs, for recency, which the reference deployment measured to matter on a small model. In ~290 words it says the plane is
closed and governed and a refusal names its scope; that a refused call is not
re-sent unchanged; that results are bounded and the whole is in the run's store,
to be read on by handle, field or section; that a failed call — a 404, a
missing file, an empty listing — is an answer and not a thing to invent around;
that **if a number is not in the view, it is not in the draft**, and every
identifier and figure is one a tool returned in this run, spelled as the tool
spelled it, and a *derived* figure — a sum, a share — is one a computation tool
printed when the plane has one; that a reference the plane can list ("the job I
have running") is looked up before the human is asked, and a lookup that finds
two candidates for a state-changing act names both and chooses out loud rather
than silently; that a multi-step change opens with a plan; that no check is
reported as passed without the tool result that shows it; and that when the
objective cannot be met the answer is what you have plus what is missing.

So **delete those sentences from your personality and from your `SKILL.md`.**
Two copies of one rule is the second emitter this framework keeps paying for,
and the day they disagree the model follows the nearer one. What belongs in
your personality is what is true of *your* deployment, and what belongs in your
manifest's `policy:` is what is true of *your* plane and no other — the three
shipped packs are the worked example (`core/skills/library/*/SKILL.md`): the
analyst keeps *a figure is printed by the computation that produced it*, the
research pack keeps its citation format and its unit rule, the coding pack
keeps *your plan is the files you read*.

If your platform genuinely has its own conduct text and wants it in the
persona, set it empty and write it there:

```python
Personality(system_message=my_prompt, conduct="")   # suppress the default
Personality(system_message=my_prompt, conduct=text) # or replace it in place
```

`conduct=None` is the default and means *the framework's current text*, read at
the moment the turn is rendered — so a run built today gets whatever the
version you pinned says, and never a copy frozen when the object was
constructed. `GOVERNED_PLANE` is exported from `judais_lobi` so you can read
what you are turning off.

**There is no CLI flag and no `PersonalityConfig` key for it**, and that is the
measure-before-default rule rather than an oversight: the escape exists because
one arrangement was foreseeable, not because anybody has needed it. A platform
spawning `judais --mission` gets the framework's conduct, which is the text it
would have written. If you find you need to suppress it from a spawned
subprocess, say so — that is evidence for a flag, and the flag would then be in
`contract.CLI_FLAGS` where a consumer can see it.

---

## 5. Capabilities: tools, the manifest, profiles and gates

### Tools, over MCP

Everything the agent can reach in a mission arrives through `tools/list` and is
dispatched through the agent's own `ToolBus`. No store, path or compute plane
is touched from the mission path; if you want the agent to be able to do
something, publish a tool.

```bash
judais --mission --mcp-url https://host/mcp "…"          # env: MCP_URL
judais --mission --mcp-stdio 'python -m my_server' "…"   # env: MCP_STDIO
```

Both flags are **repeatable and combinable**, which is how a platform composes
its own governed plane with this package's: each server's tools are namespaced
`mcp.`, then `mcp2.`, …, or by a name written on the flag
(`--mcp-stdio 'ours=python -m core.tools.serve --profile dev'`), and a
`--mcp-token` pairs with the `--mcp-url` in the same position because a token is
one server's credential. `python -m core.tools.serve` is this package's own
tools published over MCP through the same bus — so your host's profile, sandbox
and audit apply on the serving side. See the README's *Serving the built-in
tools over MCP*. Passing neither is **not** a refusal
since 0.16: the plane is then the package's own registered tools (the
built-in descriptors — the console says `🧰 … BUILT-IN tools — no server was
named`), and the refusal fires only when a skill's closed set names a tool the
host lacks — an `mcp.*` entry with no server, or a name nothing registered —
and it names those entries and lists what is here.

* **`MCP_TOKEN`** — the bearer token for `--mcp-url`. There is a `--mcp-token`
  flag and you should not use it: an argument is visible in
  `/proc/<pid>/cmdline` to every process on the host.
* **`MCP_CLIENT_NAME`** — **what this client calls itself in the `initialize`
  handshake**, and the single most easily missed line in an integration. It
  defaults to `judais-lobi`. **Set it to the agent's name.**

  A server that governs by principal still has to be able to say *which agent
  acted*, and it can only know what we tell it. The handshake once went out
  with no `clientInfo` at all, so the SDK's own default travelled, and a
  platform building its audit actor as `<person> via agent:<clientInfo.name>`
  recorded every one of the agent's calls under the SDK's name. That is not
  cosmetic: that platform's bake-off harness scores an agent by filtering the
  shared audit trail on the actor, and therefore measured the agent as having
  called **no tools at all** across a whole suite it had in fact worked through
  correctly. An agent that cannot be told apart in the audit cannot be graded,
  credited, or held to anything.

Each discovered tool is registered as a `ToolDescriptor` whose executor
dispatches `tools/call`, namespaced **`mcp.<name>`** so a server discovered at
runtime cannot shadow `fs`, `git` or `run_shell_command` by choosing their
names. Capability gating, the sandbox and the audit log apply to it exactly as
to a compiled-in tool. Its sandbox profile follows the transport: a tool
reached over HTTP is registered with `allow_network=True`, a stdio server's
tools are not, so a sandbox that denies the network by default cannot cut a
bridged tool off from the server it *is*. **A platform registering its own
`ToolDescriptor` owes the same declaration** — a tool that reaches the network
says so in its profile, or the sandbox takes it away without saying anything.

**And it owes one seam.** A tool of your own reaches a subprocess through
`core.tools.executor.run_subprocess`, and that is the *only* way the sandbox
applies to it: the bus installs the isolated runner for the length of one
dispatch, in a `contextvars.ContextVar`, and `run_subprocess` is what consults
it. A tool that calls `subprocess.run` itself runs on the host whatever
`mission_started.sandbox` says. The context follows `asyncio.to_thread` and
anyio's `to_thread.run_sync` — the two hops a dispatch actually takes — but
**not** a `threading.Thread` or a `ThreadPoolExecutor` your tool starts
itself; carry it across with `core.tools.executor.current_subprocess_runner()`
and `use_subprocess_runner(...)` if you need one.
The tool's JSON Schema is carried whole on the descriptor, so the catalogue the
model reads says `type (string: dataset|model|service)` and not just `type`;
types, `required` and enums are what decide whether a *first* call to a faceted
search works.

### Profiles: SAFE, DEV, RESEARCH, OPS, GOD

Capability gating is **deny by default**, and the profile is what grants. It
rides `mission_started.profile`, so a `safe` mission and a `god` one are
distinguishable on the wire — which they otherwise would not be.

| profile | roughly |
| --- | --- |
| `safe` | `fs.read`, `git.read`, `verify.run`, `mcp.call`. **No** shell, no interpreter, no install, no write. **The default** |
| `dev` | the above plus the code plane and writing: `fs.write`, `git.write`, `python.exec`, `shell.exec` |
| `research` | the above plus `http.read` — the web-reading tools (`fetch_page_content`, `perform_web_research`, `perform_web_search`) and nothing else. Read the web, write nothing, run nothing beyond `dev` |
| `ops` | the above plus `git.push`, `git.fetch`, `pip.install`, `fs.delete`, `audio.output` |
| `god` | `*` — everything registered |

Each level **accumulates** the ones below it. **`research` is a level and not a
flag**, carved out of `ops` in Phase 15: `http.read` used to sit beside
`git.push` and `pip.install`, so a platform whose agent had to read three
public pages had to hand it a deploy right, and `mission_started.profile:
"ops"` said something about that run that was not true. `--profile research`
reads honestly on a pane; nothing reachable under `ops` stopped being reachable.
`verify.run` in `safe` is the one
that surprises people: it ends in a subprocess too, but the command is the one
the *repository* configured rather than one the model composed, and that is the
line the code plane is drawn on throughout (§5, `sandbox:`).

A refusal is a `tool_result` with `ok: false` naming the **scope** that was
missing and the profile that grants it — `shell.exec`, and `dev` — rather than
a generic denial, because "permission denied" is the message that gets worked
around instead of read.

**`--grant` is the way past a profile without climbing it.** A mission that
needs one OPS scope — `http.read`, say, which is why web research is denied
under `safe` — had to run as `ops`, which also hands it `git.push`,
`pip.install` and `fs.delete`. `--grant http.read` adds that one scope to this
run and nothing else, and the scopes it added ride `mission_started.granted`
so a driver can render them. Three things it deliberately does **not** widen,
because none of them is a scope: the **sandbox** (`sandbox:` in the manifest,
§5, still decides how a code-plane tool is isolated — a granted `python.exec`
still runs under bwrap), the **gated set** (`--gate-tool` plus the approvals
store, below, is a decision about one call rather than about a capability), and
the manifest's **closed set** (a scope is not a tool). A scope no profile names
is refused at the door by name, and `*` is refused with the sentence saying
that `--profile god` is what that means. Where a *step* of a campaign is
narrower than the grant, its refusal says so — "granted for this run and this
step is narrower than the grant" — rather than naming a profile the operator
has already cleared.

**`mcp.call` is in the lowest profile on purpose**, and that is the one line of
this table worth reading twice: an MCP-only mission is a `safe` mission. What a
bridged tool may do is decided by the server that published it, against the
principal the handshake named (`MCP_CLIENT_NAME`, §5), and refused at the far
end — so making a platform run its agent as `dev` to reach its own governed
tool plane would have widened the *local* code plane to buy nothing.

### The skill manifest

`--skill DIR` (or `--skill DIR/SKILL.md`, or `MISSION_SKILL`) loads one
manifest — and since 0.16 `--skill <name>` loads one of the **packs that ship
in the wheel** (`core/skills/library/<name>/`: `research`, `coding`,
`analyst`; `python -c "import core.skills as s; print(s.packs())"` lists them;
each carries its SKILL.md, README, fixtures and its own `missions.yaml` eval
suite, and runs on the built-in tools with no server). A pack's fixtures are
read-only package data: stage them out with `core.skills.load(name)
.stage_fixtures(dest)` before a mission writes beside them. A manifest is
YAML frontmatter: YAML frontmatter between `---` fences, then a Markdown body. Point it
at a directory holding several skills and it refuses, listing them by name.

Four things come out of a manifest and nothing else does — and one thing it is
refused for.

**`allowed_tools` — the closed set.** A list of tool names, intersected with
what the bridge actually discovered, **in manifest order**, because the order a
skill author chose is the order the catalogue is read in.

* A bare name matches a namespaced one: write `catalog_search_assets`, get
  `mcp.catalog_search_assets`. Matching reduces on separators rather than on a
  list of known prefixes, so a manifest written in any convention resolves —
  including one nobody has invented yet. An entry matching *two* discovered
  tools is a refusal asking you to name the namespace, rather than a coin flip.
* Suffix an entry with **`?`** to mean *use it if the server offers it* — the
  same marker the `inputs:` grammar uses for an optional input. Everything
  without it is required.
* **A manifest naming a missing required tool refuses loudly**, listing every
  missing name *and* everything that was on offer. Never a silent narrowing and
  never a run: a mission missing the tool that answers its question will answer
  it from the model's memory instead, and the transcript will look completely
  ordinary. A closed set where every entry is optional and none was discovered
  is refused for the same reason.
* A closed set naming a **code-plane tool that runs on this host** is refused
  unless the manifest also declares `sandbox: bwrap`. See below.

**Prompt text.** The operational frontmatter fields and the whole Markdown
body, appended to the personality's system message — who you are, then what you
are doing. Six fields are rendered first, in this order: `when_to_use`,
`inputs`, `retrieval_strategy`, `ranking`, `policy`, `evidence_requirements`.
`output_format` is rendered **last**, after the body, because it is the
instruction a model is acting on when it stops.

**Fields this loader has never heard of are rendered into the prompt anyway**,
as `Label:\nvalue`. A skill is content, and a harness deciding that an
unrecognised field is noise would be the framework overruling the platform on
its own operational knowledge. Only the structural keys are held back — `name`,
`skill_id`, `version`, `description`, `allowed_tools`, `grounding`,
`sdk_import` — because each already reaches the model another way.

**`grounding` — the identifier grammar, and the tiers you switch on.** A
mapping, interpreted by `core/runtime/grounding.py` and never by the loader.
Absent means no validator is built and the transcript's grounding report stays
`None` rather than claiming a clean check: a check that could not run reports
*no opinion* and never a pass, because a fabricated "grounded" is a governance
claim. The keys are `identifier_pattern`, `number_pattern`, `figures_from`,
`ignore`, `max_repairs`, `must_cite`, `claim_table`, `reading`, `critic` and
`planes`; anything else is refused by name. `reading`, `critic` and `planes`
are **off by default** and are the ones a platform has to decide about:

```yaml
grounding:
  identifier_pattern: '\b(?:corpus|labels|run)\.[a-z0-9_]+\b'
  claim_table: true
  reading: true                 # refused without claim_table: true
  critic: true
  planes:
    sdk:  {tools: [mcp.run_python_code], claims: ['I used the SDK', 'I recomputed']}
    code: {tools: [run_shell_command], claims: ['I ran']}
```

* **`figures_from:` says which tool MEASURES the quantity your
  `number_pattern` describes.** Unset — the default, and what every manifest
  written before it means — a figure is supported if it equals any figure
  anywhere in the run's evidence. On a plane whose tools emit diagnostics
  that is nearly every small integer: measured on the `coding` pack, a
  `patch apply` result carries a match count, byte offsets and a hash, and an
  agent that never ran the tests came back `grounded` having written
  "3 passed". `figures_from: [verify]` grounds a figure against those tools'
  results and nothing else, matched with `same_tool` so a bridged spelling
  counts; the check's row then reads `scope: [verify]`, and the repair turn
  says "in no verify result" rather than the generic "in no tool output",
  which under a scope would be false. It narrows **figures only** —
  identifiers keep the whole evidence set, because an identifier legitimately
  arrives from any tool that names one. Evidence with no provenance (a
  library caller's plain strings) is out of a scope rather than exempt from
  it, so scope figures only where the evidence comes from a mission's own
  result store. It is refused without a `number_pattern`: a scope over a
  check that is switched off narrows nothing and reads in a report as though
  it did.
* **`planes:` is how a platform declares its tool families — the framework
  never learns their names.** A plane is a set of tools and the phrases an
  answer uses when it claims them, and the check fails an answer that claims
  one nothing on it was dispatched from **this run**. "I used the SDK to
  recompute the figure" carries no identifier, no figure and no claim-table
  entry, so every mechanical tier reports *nothing considered* and the sentence
  goes out grounded while describing work that did not happen — the single most
  expensive sentence in a governance report to get wrong, because a reader who
  believes the SDK ran believes the number was computed rather than remembered.
  A plane with no `tools`, or no `claims`, is refused: a half-declared plane
  silently checks nothing.
* **`critic: true` does not need a frontier key.** The provider resolves
  **local first** — with `LOCAL_API_BASE` set, the critic is the same weights
  the mission already leased, given an adversarial prompt. A hosted provider is
  reached **only** where the deployment wrote `critic: {enabled: true}` into
  `.judais-lobi.yml` or `~/.judais-lobi/critic.yml` *and* a key resolves.
  Posting a governed draft to another company is a handling decision a platform
  makes explicitly rather than one a framework makes by noticing an API key in
  the environment. With neither, the row says `skipped` and names what was
  missing. The verdict is a `critic` row in `grounding.checks` marked
  `advisory: true`, **beside** the record's `grounded` and never inside it.
* **`reading: true` needs `claim_table: true`** and is refused without it. It
  is the one tier that spends model calls — two per claim, capped at twelve —
  which is why it is off and why it runs last, after every mechanical check.

None of the three is on by default anywhere, and a platform should **measure**
before switching one on for good: §9 is the harness, and `--replay` lets the
decision be made on runs the platform already has.

**`sdk_import` — what the platform calls itself to Python.** A single module
name, e.g. `sdk_import: acme`. A list or a number is refused rather than
coerced, because `sdk_import: [acme]` would render as ``import ['acme']`` in a
sentence handed to a model, and the model would write that line.

It exists for the swarm. `--swarm` plans a mission as steps, each tagged with a
**rung** — how the step will be done:

| rung | what it means | offered when |
| --- | --- | --- |
| `tool` | a registered tool | always |
| `code` | code via a code-execution tool | always |
| `code+sdk` | code that also fetches platform data itself, `import <sdk_import>` | **only when `sdk_import` is declared** |

A manifest that declares none does not get a vaguer sentence — **it does not
get the rung**, and the planner's prose lists only the rungs it may use, with
the plan validator refusing the others by the same list. "Import the platform
SDK" with no SDK named is an invitation to invent a module, and a 20B accepts
the invitation. This is also why the name is a manifest field rather than a
constant: the framework drives whatever platform it is pointed at, and it
cannot know what that platform is called.

**`sandbox` — the code plane never arrives by accident.** A closed set naming a
tool that runs code *the model composed* must also declare `sandbox: bwrap`, or
the resolve refuses, naming the tool, the missing declaration and the fix:

```yaml
allowed_tools: [governed_read, run_shell_command]
sandbox: bwrap
```

A governed mission that can run arbitrary code on the host without isolation is
not a hazard a hosted platform should discover from a transcript, so it is a
refusal at the door — before the model is asked anything, because a mission
that has already run has already run whatever it ran.

* **Which tools those are is derived from scopes, not typed out.** Any
  descriptor asking for `shell.exec`, `python.exec` or `pip.install` — today
  `run_shell_command`, `run_python_code` and `install_project`, and whatever is
  registered next, on the day it is registered.
* **The rule is `tool_key` equality, and a bridged spelling does not count.**
  `mcp.run_python_code` is a tool on a discovered server — the mission sends
  `tools/call` and the interpreter runs on the far end — so `sandbox: bwrap`, a
  wrapper this bus puts around a subprocess *it* spawns, would isolate nothing
  about it. The bare name is this process's own descriptor and is gated; a
  namespaced one is the server's and is not. **A platform that bridges a shell
  is responsible for the isolation on the server side**; what this harness
  governs it with is the closed set, the `mcp.call` capability and
  `--gate-tool`, and it does not claim to have sandboxed it.
* **An optional entry counts.** `run_shell_command?` is a manifest that permits
  running shell commands; whether the gate applies must not depend on what a
  server happened to advertise this morning.
* **Declaring it is half. Getting it is the other half.** At mission time the
  resolve is told what the bus is actually isolating with; a manifest that says
  `bwrap` and gets a bus running `none` is refused, because a manifest that
  asked for isolation and did not get it asked for nothing.
* **`sandbox: none`** is the explicit *no isolation was asked for*: accepted and
  inert for a manifest with no code-plane tool, refused for one that has them.
  Any other value is refused when the file loads — `sandbox: firejail` asks for
  isolation this framework has no backend for, and reading it as good enough is
  how a declaration becomes decoration.
* It is **rendered into the prompt** (`Sandbox: bwrap`) like any other
  operational field. Network is denied inside the namespace, and an agent that
  has not been told reads `ENETUNREACH` as a broken tool and spends a turn
  retrying it.

### Without a manifest

`--skill` is optional and you should treat it as mandatory. With no manifest
the mission is **offered every discovered tool** and **builds no grounding
validator**, so the fabrication check that exists for exactly this surface
never runs. The CLI prints a yellow warning saying so; that warning is the only
thing between a deployment and an ungoverned mission whose transcript looks
identical to a governed one. It is a fallback, not a default posture.

### The results store

A tool result is capped at 32 KB before it enters the transcript — head and
tail with an explicit marker. The **whole** result stays in a per-mission store
under a short handle, and the model can ask for one field:

```
mission_result(handle="r1", path="result.actors[0].score")
```

A few dozen bytes instead of two hundred kilobytes. The store holds no
capability of its own: every byte in it arrived through a dispatch that was
already gated, audited and inside the closed set, so reading it back is not a
widening. It is registered on the bus for the length of one run and withdrawn
after it. A consumer sees the handle on every `tool_result`, and
`tool_result.output` carries the result **whole** — the bound is what the
*model* is shown, not what a watcher is.

### Gates and approvals

`--gate-tool NAME` (repeatable) names a tool this deployment **offers and
gates**. It appears in the catalogue, marked. If the model names it, the call
is **not made**: the mission emits `gate_requested` with the proposed arguments
verbatim and, with no `--control` channel open, ends at outcome
`awaiting_approval`.

The arguments travel verbatim because what a person approves has to be the
bytes that would run.

**No flag on a mission run answers a gate.** A framework that could approve its
own proposal would be a framework whose gate is a formality, and there is no
code path that can move a record to *approved* from inside a run — a test greps
for it.

The answer arrives instead as a **durable record written from outside the
run**. Unless `JUDAIS_LOBI_APPROVALS` says otherwise, a gate writes
`.judais-lobi/approvals/<id>.json` holding the tool, the arguments verbatim,
the objective and the run that asked, and the id rides
`gate_requested.approval_id`. Three ways to answer it:

* **Your platform calls the library.**
  `core.runtime.approvals.ApprovalStore(root)` → `.get(id)`,
  `.decide(id, approve=…, decided_by=…, note=…)`, `.pending()`,
  `.reconcile(live_run_ids)`. **This is the integration point**, and it is why
  the approve/refuse commands below are not in `contract.CLI_FLAGS`: a platform
  decides in its own process, where it knows who the person is.
* **While the run is still standing at the gate**, over `--control`, which is
  §7 — the gated call is then dispatched in that same step and the mission
  carries on.
* **An operator runs the command.** The mission CLI has an approve/refuse mode
  that builds no agent and asks no model. It is a person's surface, so it is
  not in the published set and may move; drive `ApprovalStore` instead.

`decided_by` is free text and only its **emptiness** is refused. This framework
has no principal system and will not invent one: *who counts as a person* is
your question, and your answer belongs on top of this mechanism rather than
inside it.

You then resume by spawning a *new* mission with `--approval <id>` (env
`MISSION_APPROVAL`), which widens the closed set by exactly one tool, for
exactly one run, after exactly one person said so. The approval is **spent when
the tool is dispatched**, so a resumed run that never reaches it leaves the
decision unspent rather than burning it on nothing; a pending, refused, spent
or abandoned record is refused at the door, naming the state. Nothing defaults
or expires into a yes.

**Read the widening off `mission_started.gated`.** There is no field announcing
an approval on the stream — the approved tool is simply not in the gated list
for that run, which is already the statement of what the run will not call.
Keep passing the full `--gate-tool` list on the resumed spawn; `--approval`
does the subtraction, and doing it yourself as well would make the flag's
narrowness your bug to maintain.

> **A gate name resolves the way a manifest's does, and an unresolvable one is
> a refusal.** `--gate-tool` asks the same matching question `allowed_tools`
> asks, so you may pass the wire spelling off your own tool table
> (`compute_cancel_job`) or the bridge's namespaced name
> (`mcp.compute_cancel_job`). Either works, and the resolved name is what the
> `🔒 gated:` line prints and what the loop enforces. A name that matches
> **nothing** is a refusal naming it and listing every tool that *was* offered;
> a name that matches **two** is a refusal asking you to name the namespace.
> Neither is dropped quietly, and that is the fix for a real bug: exact
> membership was the rule until it was not, every gate one platform passed in
> its own spelling matched nothing, the `🔒 gated:` line never printed, and the
> call somebody was meant to approve was dispatched like any other.

---

## 6. Durability: the run store, resume and replay

`mission_started.run_id` names a directory under `.judais-lobi/runs/<run-id>/`
in the harness's working directory — moved by `JUDAIS_LOBI_RUNS=<path>`, kept
nowhere by `JUDAIS_LOBI_RUNS=none|off`, in which case the field is absent.

### What is in a run directory

| file | what it holds |
| --- | --- |
| `events.jsonl` | every record that went on the stream, as fsync'd append-only `{seq, at, record}` envelopes. **Written before the record reaches the `--events` sink**, so the sink is a client of the log and not a second copy: a pane that lost the pipe reads the same bytes off disk |
| `model.jsonl` | one fsync'd line per model call, in call order: the request (`messages` and the rest of what went out), the reply, and the `tool_calls`/`usage` side channels read off the backend |
| `tools.jsonl` | the tool plane as this run met it. Line one is the catalogue (`"call": 0`); every line after it is one dispatch with its arguments and its result, including the MCP `structuredContent` that never travelled on the event stream |
| `meta.json` | the run's own facts, replaced atomically — the objective, the flags that decide *which run this is*, and `replay_of` on a replay |

`seq` is the store's numbering and **never travels on the wire**.

**The two logs are scrubbed less than the event log: credentials only.** The
redactor takes five families out of a record on its way to a pane; here only
the secret sweep runs, because absolute paths and this host's name are *the
model's input*, and a recording whose input was rewritten is a recording of a
prompt nobody ever sent. A credential is never written down in this directory
whichever file it arrived in.

### What a driver can do with it

* **Answer "did that run ever finish?"** A log whose records include
  `mission_finished` is a run that closed; one without is an **orphan**. Every
  mission reconciles orphans on the way in — a run untouched for 60 seconds
  with no `mission_finished` gets one appended, and the approvals it left
  pending are abandoned with it — so a follower's stream ends rather than
  stopping mid-sentence.
* **Join late.** `RunStore.since(cursor)` and `follow(cursor, stop=…)` replay
  from a `seq`.
* **Resume.** `judais --mission --resume <run-id>` with **no objective** — it
  comes off the record, and a different one is refused naming both. Records go
  on being appended to the *same* directory and there is **no second
  `mission_started`**; the first new `step_started` carries
  `resumed: {from_seq, steps_replayed}` instead, which is the frame a follower
  holding a cursor will actually receive.

  A run that ended `answered`, `answered_with_caveat` or `budget_exhausted` is
  refused: those are conclusions. `incomplete`, `awaiting_approval` and a log
  with no ending at all are resumable. A **staged** (`--swarm`) run is refused
  today, and the refusal names the steps that are done. `max_steps` counts the
  whole run, so killing and resuming cannot buy extra steps — and a run started
  with no ceiling resumes with none, rather than the resume inventing a bound
  nobody set; passing `--mission-steps` on the resumed spawn asks for that many
  *further* ones. The credential is deliberately not persisted: `MCP_TOKEN` is
  read from the resuming process's own environment.
* **Replay.** `judais --mission --replay <run-id>` (env `MISSION_REPLAY`) runs a
  finished mission **again** out of its own recording — the real loop, the real
  grounding validator, replies served by ordinal and tool results off disk, so
  **no server is dialled and no model is asked** — into a **new** run directory
  carrying `replay_of` and any prompt `drift`. This is how a grounding change is
  scored on last week's runs, on a laptop, and it is what the conformance kit in
  §10 spawns. It is not `--resume`: that continues an unfinished run against a
  live model.

---

## 7. Bounding a run, steering one, and stopping one

**Nothing bounds a run that nobody bounded.** Both ceilings are an operator's
and both are unset by default: `--mission-steps` (no ceiling; `max_steps: 0` on
the stream) and `--mission-seconds` (no wall clock). This harness imposes no
step budget, because how many turns a question is worth is not a thing it can
know — a mission once graded as an agent that "stops dead" had simply run out
of room. When you do set a step ceiling it counts parse-error turns as well as
tool turns. The wall clock is checked between steps and before each model call,
and one clock covers the whole of a `--swarm` turn; a call already in flight is
not interrupted, so the real bound is that plus one round trip.

Running out is `outcome: "budget_exhausted"` with
`budget: {which, limit, spent}` on `mission_finished` — present **exactly when**
that outcome is, so a driver may branch on the outcome and index the field.
`which` is `steps`, `seconds`, `bytes` or `tokens`; the last two are declared
and not yet emitted. `spent` is not always `limit`, because a wall clock is
noticed a little after it runs out.

### The supervisor

What stops a run that is going nowhere is the supervisor, and it watches for
**repetition** rather than for length. Five mechanical signals:

| signal | what fires it |
| --- | --- |
| `repeated_call` | the same call returning the same result three times within the last six acts. *Not* three in a row — a stall threads productive-looking reads between its repeats |
| `rejected_replies` | three replies running that the loop could not act on |
| `no_new_evidence` | four steps in which no act was new. An act is new if **either** its call **or** its result is one the run has not seen — so a polling loop (same call, new result) and an edit loop (new call, same result) are both progress |
| `oscillation` | A B A B — alternating between two calls rather than going forward from either |
| `failed_gate` | swarm only, and *reported* rather than noticed: a plan step ran and what came back is not what the plan asked for |

Each fires one plain model call asking what the pattern means, and the verdict
rides the next `step_started` as `review: {signal, verdict, note?, reviews_left}`.
Four verdicts:

* `progressing` — not a loop; the run carries on untouched.
* `nudge` — one instruction would unstick it. The note goes in front of the
  model, and the same record carries `injected`.
* `stuck` — it cannot be unstuck. The run is asked for a best answer and ends
  with `reason: "stuck"` beside whatever outcome that answer earned — usually
  `answered`, so **a driver must not read `stuck` as a failure**.
* `replan` — swarm only, at a step-level review: the step is fine and the plan
  is wrong, so the plan is redrawn around what has already succeeded.

At most **three** reviews a run, and the last cannot say `progressing`. That
cap is the whole of the endless-loop catch, and it is arithmetic rather than
judgement on purpose: each review is a model call and each verdict is the
model's opinion of itself, so a run that can keep asking for another opinion is
a run that can loop forever with a review turn in it.

One signal is excepted: a `progressing` verdict on `no_new_evidence` is
**refunded** — not counted against the three — twice. The other four are
demonstrated repetition and the arithmetic is right for them; an absence of new
evidence is something a healthy run shows honestly for a stretch, and ending
such a run by counting is what replacing the step budget was for. The
threshold still rises on every `progressing` (4 stale steps, then 8, then 12),
and after two refunds the count applies again, so a run that is genuinely stuck
is still wound up.

The supervisor is **built by default**: `Bounds()` with no `supervisor=` gets
one made from the run's own model and shared with every child, so a turn has
one review budget the way it has one clock. `Bounds(supervisor=NO_SUPERVISOR)`
is the explicit opt-out — a run nothing but a clock or a person can stop.

### `--control` — the channel into a running mission

`--events` is what a mission says; `--control` is what it can be told, and
until it existed the only lever on a running turn was SIGTERM. It takes the
same forms as `--events` in reverse: `fd:N` (what a platform uses — keep the
*write* end of a pipe and the mission never has a path on disk to race anybody
for), a FIFO, a path, or `-` for stdin. One JSON object per line; the
vocabulary is closed.

| the UI affordance | the command | what happens |
| --- | --- | --- |
| "steer it" / a message typed at a running turn | `{"control": "inject", "text": "…"}` | appended as a `user` turn immediately before the next model call, and reported back as `step_started.injected: ["…"]` — the only trace on the stream that anybody spoke |
| "skip this" / an interrupt that is not a stop | `{"control": "cancel_step"}` | the calls of the current step that have not been dispatched are skipped, the model is told in as many words and asked again. **A tool already running is never killed.** An ask that arrives too late is a no-op and says so |
| "stop" | `{"control": "cancel"}`, then SIGTERM if the process must go | the mission winds up at its next check, keeps its transcript, and writes its own `mission_finished` (`incomplete` + `reason: "cancelled"`). The process exits *normally* — a platform asked the mission to stop, not the process to die of a signal nobody sent |
| an approvals UI, while the run is standing at the gate | `{"control": "gate_decision", "approval_id": "ap_…", "approve": true, "decided_by": "dana", "note": ""}` | the gated call is dispatched **in that same step** and the mission carries on; the record is written through the same `ApprovalStore` the `--approval` path reads, `decided` then `spent`, by the name you sent. A no is recorded as a refusal and the model is told |

With a channel open a gate **waits** rather than ending the run: bounded by
`min(what is left of --mission-seconds, --gate-wait)`, which defaults to 300 s.
So a driver may see a `gate_requested` followed, under the same `index`, by the
`tool_call`/`tool_result` for the call it asked about. **Nothing times out into
a yes**: the wait running out ends the mission at `awaiting_approval` exactly as
it always did, with the record left `pending` for `--approval` on a later turn.
`decided_by` must name somebody, and a command signed by nobody is dropped.

A malformed line, an unknown word, an `inject` with no text or a decision
signed by nobody is dropped with **one** sentence on stderr and the run carries
on; a channel nobody writes to, or whose writer goes away, is not an error.
**Commands are not events**: the run answers them by doing the thing.

On `--swarm` there is one channel for the turn, shared the way the wall clock
is, and it reaches the sub-mission that is running.

---

## 8. Providers

Four, and `--provider` chooses one. `ELF_PROVIDER` is the environment form.

| provider | credential | default model | notes |
| --- | --- | --- | --- |
| `local` | none | `LOCAL_MODEL`, then the endpoint's own `/models`, then `local-model` | **the first-class target.** `LOCAL_API_BASE` points at any OpenAI-compatible endpoint |
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` | the fallback when nothing is stated, which is why you should state something |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-opus-5` | needs `judais-lobi[anthropic]`. No JSON mode: constrain output with `--protocol native`, not with a response format |
| `mistral` | `MISTRAL_API_KEY` | `codestral-latest` | |

**State the provider and the model.** Both have defaults and both defaults fail
silently in a different way. With neither set, one platform's first production
message fell through to the hosted OpenAI backend and died on
`Missing credentials` — a turn that reads as a broken agent, and a backend
nobody meant to select.

**`local` and `anthropic` are never fallen back away from.** Asking for the
endpoint on this host and being answered by a hosted provider is the opposite of
what was asked, and for a mission prompt it would send the prompt off the host.
A missing key is not evidence that a local server is down: `local` talks to a
port on this host that usually wants no credential, so it is deliberately absent
from the key table the fallback logic consults.

### An OpenAI-compatible local endpoint is the target this is built for

vLLM, TensorRT-LLM and llama.cpp all serve one, and the whole `local` path is
written against that shape rather than against any one of them:

```bash
export LOCAL_API_BASE=http://127.0.0.1:8000/v1
export LOCAL_MODEL=org/model-name          # or let it read GET /models
judais --mission --provider local --mcp-url … "…"
```

Three things follow that a hosted-only integration never has to think about:

* **`usage` is routinely absent**, because many local servers report nothing.
  That is why the field is optional and why a missing one must never be read as
  zero (§3).
* **The prompt prefix is money.** A served endpoint's prefix cache is keyed on
  bytes, so the harness keeps the stable parts of a request stable — whitespace
  and the most-constant-first ordering are deliberate, and `--replay` reports
  *drift* when a request differs from a recorded one, which is how that promise
  is tested rather than asserted.
* **The critic can be local too.** `critic: true` in a manifest's `grounding:`
  block resolves local first, so a deployment running entirely on its own
  hardware still gets an adversarial second opinion (§5).

---

## 9. Evaluating your integration

A mission is a question about a deployment's data, and this framework has none
— so a platform keeps its suite **in its own repository**, as YAML or JSON, the
same way it keeps its personalities and its skills. Nothing in `core/eval/`
knows a tool name, an asset id or a deployment.

```yaml
name: my_platform
tools: [mcp.catalog_search, mcp.catalog_get]     # the plane the suite is written against
identifier_pattern: '\b[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+\b'
assets:
  corpus.example: a corpus, and the only one with a label set
missions:
  - key: lineage_archaeology
    flag: chaining
    split: train            # or `test` — the held-out half
    prompt: Where did the label set we hold come from?
    must: [names the parent corpus by asset id, from the lineage]
    must_not: [asserting the binding from the two names resembling each other]
    expects_tools: [mcp.catalog_get]
    expects_outcome: answered
    expects_grounded: true
    flags: [--swarm]        # every --token must be in contract.CLI_FLAGS
```

`python -m core.eval` has three subcommands, and only one of them needs a model:

```
python -m core.eval check --suite path/to/suite.yml
python -m core.eval run   --suite path/to/suite.yml --out DIR -- <your spawn line>
python -m core.eval score --suite path/to/suite.yml --runs DIR
```

* **`check`** refuses a suite that cannot be graded, before anybody spends a GPU
  on it. Run it in CI.
* **`run`** spawns one mission per case. **This is the one that needs a model.**
* **`score`** grades run directories that already exist — **the no-GPU path**.
  Yesterday's runs can be re-scored against today's rubric, and a grounding
  change can be scored on runs it was not present for. Combined with `--replay`
  (§6) it is how a platform measures a change on runs it already has.
* **`measure`** runs the same suite over a **matrix of configurations** against
  one endpoint and prints the differences — `run` answers *how did this
  configuration do*, `measure` answers *which configuration is better*. It is
  what ROADMAP §3's "measure before default" is done with: nothing here becomes
  on-by-default off one number. See `EVAL.md` §12.

A fourth, **`live`**, lands in **0.16**: a platform's own suite driven against a
running deployment rather than against an archive.

Three things to know before writing a suite, all of them things a deployment
got wrong first:

* **The split is mechanical, not a judgement.** `split: test` is held out, and
  the report never blends the halves. A suite tuned against the half it is
  scored on measures the tuning.
* **`tools:` and `assets:` are what make a suite checkable.** `check` refuses a
  suite whose mission expects a tool the plane does not have or whose prompt
  names data the platform does not hold. One deployment shipped a
  `disambiguation` mission that was quietly measuring `absence` for a month, and
  marked an agent FAIL against a question it could not have answered.
* **The spawn line after `--` is yours.** Provider, model, tool plane, skill,
  protocol — those are the variables being measured, and a harness with opinions
  about them would be measuring itself. The harness adds exactly three things:
  the objective, `--events fd:N`, and `JUDAIS_LOBI_RUNS` pointed inside the
  mission's own directory.

`EVAL.md` is the whole guide; its suite-format section is the reference for the
YAML above.

---

## 10. The conformance kit

**`tests/conformance/` is two files you copy into your own repository.** That is
the deliverable of this whole page: an afternoon's integration is only finished
when there is a test that goes red the day the contract breaks.

```
cp <judais-lobi>/tests/conformance/conftest.py         yourrepo/tests/
cp <judais-lobi>/tests/conformance/test_conformance.py yourrepo/tests/
```

Then edit **one dict**, `CONFORMANCE`, at the top of the second file — and
nothing else, in either file, ever.

| key | what you put in it |
| --- | --- |
| `pin` | the release you integrated against, as `pip` reports it. Read it out of whatever one file already holds your pin rather than typing a version twice |
| `schema_version` | `contract.SCHEMA_VERSION` at that release |
| `reads` | **the table that matters**: every event your bridge has a branch for, and every field it takes off one |
| `flags` | every flag your spawn line passes |
| `env` | every variable you export into the child |
| `outcomes` | every outcome word you branch on |
| `exit_clauses` | every clause of §3's exit contract you build behaviour on |
| `spawn` | how you start the harness, and **one recorded run to replay** |

### What it asserts

1. `contract.SCHEMA_VERSION` is the one you wrote the file against. **The
   load-bearing line**: the harness bumps it exactly when a consumer has to
   change.
2. Every event in `reads` is one the harness still emits.
3. Every field in `reads` is one the harness still **declares** — required or
   optional. This is the drift that is otherwise silent: a renamed field reaches
   your bridge as `None`, and the turn renders with the content simply gone.
4. Every flag, every variable, every outcome word and every exit clause you
   rely on is still in the published set.
5. The pinned version is the installed one.
6. **A real mission runs**, and `contract.conforms()` is asserted on every
   record it emits — plus the exit contract's own promises: that the stream is
   not empty, that it opens with the posture, that it closes with
   `mission_finished`.

Assertion 6 is what makes this more than a comparison of two lists, and it
costs nothing to run: the spawn is a `--replay` of a run that was already
recorded (§6), so the real loop, the real grounding validator and the real
emitters run with the replies served off disk by ordinal. **No model, no API
key, no MCP server, no GPU, no network.** Any run directory you have archived
will do. Put it on the same CI trigger as everything else.

### Why a copy and not an import

The thing being tested is your *restatement* of the contract — the field names
your bridge writes as literals because a served tier cannot import an agent
framework, the flags your spawn line passes, the outcome words you branch on. A
restatement with a test is a duplication; a restatement without one is a
divergence waiting for a deploy, and that is exactly what one deployment
shipped: a bridge reading `record.get("audit_ref")`, a harness that had renamed
nothing *yet*, and no test anywhere comparing the two.

### Make your copy shorter

The shipped `reads` names all ten events and every field, because this
repository runs the kit against itself and a template that had fallen behind the
contract would be worse than none. **Yours should name what you actually
index.** An event you have no branch for does not belong in it — dropping an
unknown record is correct and is what the compatibility rule expects, but it
should be a decision somebody made rather than a frame nobody noticed, which is
what writing the table down makes it.

`tests/conformance/README.md` is the same instructions, beside the files.

---

## 11. Versioning, pinning, and the 1.0 freeze

### The compatibility rule

`SCHEMA_VERSION` is carried on every `mission_started`.

* **Additive is minor.** A new event, or a new *optional* field on an existing
  event, does not bump it. Safe because consumers drop record types they do not
  know — and §10 is how "we drop it" stays a decision rather than an accident.
* **Breaking bumps it.** Renaming a field, removing one, moving one out of the
  required set, or changing what an existing required field means. A consumer
  that pins `contract.SCHEMA_VERSION == 1` finds out at import, which is the
  only moment at which finding out is cheap.

### The 1.0 freeze

**From v1.0.0, `SCHEMA_VERSION` is frozen for the whole 1.x major.** Adding
events and optional fields remains a minor release; anything that would break a
1.x consumer is 2.0 and a new `SCHEMA_VERSION`. `CONTRACT.md`'s "1.0 — the
freeze" section is the promise in full, and it is the thing to read before you
write `schema_version` into your conformance kit.

### How a platform pins

**One file, one line, one git tag**, and nothing else in the platform states the
version. A deploy script reads that file and checks the tag out on the host as a
**detached git checkout** — not an rsync — then installs it into a named venv.

The checkout is the point. One pool's copy used to arrive by rsync, and an
rsynced directory has no version: `git describe` had nothing to describe and
`pip show` reported whatever was installed last, so "which harness answered that
mission" could only be answered by reading code on the host. **A pin nobody can
verify on the host is a pin in name only**, which is why a deploy script wants a
`doctor` mode that answers it in one command.

Then pin the *contract* as well as the tag:

```python
from core.runtime import contract

assert contract.SCHEMA_VERSION == 1        # fails at import, which is cheap

problems = contract.conforms(record)       # [] when the record is fine
```

`conforms` is pure, standard library only, and imports nothing this repo owns —
a consumer that cannot import an agent framework can vendor that one file and
have the whole seam. It checks that the record names a declared event, that
every required field is present, and that any `schema_version` it carries is one
the contract understands. It does not check types and does not object to extra
keys, because an added optional field is a minor change and a checker that
failed on one would make every additive release a breaking one.

### Testing a new release against your platform

**A new judais-lobi release is tested by this sequence and by nothing else:**

1. On a branch in *your* repository, bump the pin file to the new tag.
2. Run the conformance kit (§10) and whatever other tests cross the seam. A
   served tier cannot import an agent framework, so its bridge restates the
   field names as literals, and those tests are the only thing standing between
   a renamed field and a pane that renders a turn with the content silently
   missing.
3. Deploy to a staging pane and drive **one real mission** through it. A
   consumer-side conformance check is not the same thing as an agent that
   actually answered.
4. Have the deployment report which tag it is on, and whether the version `pip`
   reports agrees with it.

### Cutting a release (for this repository's own maintainer)

1. Bump `VERSION` in `setup.py`. That constant is what `pip` reports and what a
   deploy doctor compares its checked-out tag against.
2. Update the version in `README.md`'s status line —
   `tests/test_docs_track_the_code.py` holds the README against `VERSION`, and
   `setup.py`'s summary derives from it rather than repeating it.
3. Tag `vX.Y.Z` and push the tag. `.github/workflows/pypi-release.yml` builds
   from a clean export of the tag, refuses a tag that disagrees with `VERSION`,
   and uploads.

---

## Appendix — what must never enter the framework

judais-lobi drives whatever platform it is pointed at. Four things had stopped
believing that, each one shipped inside the package. They are listed here as a
shape to recognise:

* **A platform's paths.** A personality search that tried three fixed
  directories under `$HOME` and a sibling of the cwd, with another repository's
  source layout frozen into a constant. That is one developer's laptop,
  installed onto every other machine.
* **A platform's SDK name.** An `import <platform>` written into a swarm rung
  sentence, under a comment promising that a role never names a platform's
  particulars. It is a manifest field now: `sdk_import`.
* **A live hostname or a real credential variable in `--help`.** An example is
  copied before it is read. A hostname in `--help` is a hostname published to
  everyone who ever runs `--help`, and a token named in argv is a token visible
  in `ps`.
* **Absolute paths in tests.** Two suites were anchored to artifacts on one
  machine and skipped everywhere else, silently, with nothing telling anyone how
  to opt in. They read an environment variable now and skip with a sentence
  naming it.

And the general form, which is the only one worth memorising:

* **A platform's tool names**, anywhere outside a manifest. The bus's catalogue
  is the one description of a tool; a second copy disagrees with the first the
  day a server changes a description.
* **A personality as a default.** The framework ships no personality it does not
  contain, and it does not invent one. A missing personality is a refusal naming
  what was consulted, not an agent running on whatever it was handed while still
  calling itself by the right name.
