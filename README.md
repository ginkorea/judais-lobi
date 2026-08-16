# 🧠 judais-lobi

> Artifact-driven. Capability-gated. Endpoint-aware.
> Not a chatbot. A kernel.

---

[![PyPI](https://img.shields.io/pypi/v/judais-lobi?color=blue\&label=PyPI)](https://pypi.org/project/judais-lobi/)
[![Python](https://img.shields.io/pypi/pyversions/judais-lobi.svg)](https://pypi.org/project/judais-lobi/)
[![License](https://img.shields.io/github/license/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/blob/main/LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/commits/main)
[![Repo Size](https://img.shields.io/github/repo-size/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi)
[![Code Size](https://img.shields.io/github/languages/code-size/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi)
[![Issues](https://img.shields.io/github/issues/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/issues)
[![Stars](https://img.shields.io/github/stars/ginkorea/judais-lobi?style=social)](https://github.com/ginkorea/judais-lobi/stargazers)

---

## 🔴 JudAIs & 🔵 Lobi

<p align="center">
  <img src="https://raw.githubusercontent.com/ginkorea/judais-lobi/master/images/judais-lobi.png" alt="JudAIs & Lobi" width="420">
</p>

Two agents. One spine.

* 🧝 **Lobi** — whimsical Linux elf, creative, narrative, curious.
* 🧠 **JudAIs** — strategic adversarial twin, efficient, ruthless, execution-first.

They are no longer just terminal personalities.

They are evolving into a **local-first, contract-driven autonomous developer system**.

To find out why read the [Manifesto](https://github.com/ginkorea/judais-lobi/blob/master/MANIFESTO.md)!
---

## Why This Exists

Frontier models are expensive, rate-limited, and increasingly censored. If you want to build serious systems, you should not have to rent your agency by the token, or wait for policy filters to decide what is “allowed.” Judais-Lobi is built so you can run your own stack, control your costs, and decide your own boundaries.

## Who It’s For

* Builders who want **lower inference cost** and **predictable behavior**.
* People who dislike censorship and want **model choice** instead of vendor lock-in.
* Engineers who care about **deterministic runs** and **auditable decisions**.
* Anyone who wants an **extensible workflow engine** rather than a chat toy.

## Quickstart

1. Install:
   `pip install judais-lobi` — or, from a checkout and with everything a mission
   needs, `pip install -e '.[mission]'`.
2. Set an API key (OpenAI is the default today):
   `export OPENAI_API_KEY=sk-...`
3. Run a task:
   `lobi "summarize this repo"`
4. Use tools explicitly. Tools are deny-by-default: the `safe` profile can read
   the filesystem and git but not run a shell, so running a command needs the
   `dev` profile —
   `lobi --profile dev --shell "ls -la"` (`--profile safe|dev|ops|god`, or
   `JUDAIS_LOBI_PROFILE`; without it, `lobi --shell` refuses and names
   `shell.exec` and the profile that grants it).

Three commands are installed, one per agent. They take the same flags; only the
personality differs.

| command | agent |
| --- | --- |
| `lobi` | 🧝 the mischievous one — a general assistant |
| `judais` | 🧠 the sharp one — a general assistant |
| `tai` | the mission-agent personality — governed tools over MCP, cites every claim, never sees source. Its personality file belongs to the deployment that operates it; `tai` finds that file or refuses, naming what it consulted |

`python main.py [lobi|judais|tai] <message> [flags]` reaches the same three
without installing anything, and `python main.py --help` lists them.

### Local inference

`--provider local` talks to any OpenAI-compatible endpoint — `vllm serve`,
llama.cpp's server, LM Studio, Ollama's `/v1` shim:

```bash
export LOCAL_API_BASE=http://127.0.0.1:8000/v1   # note the /v1
export LOCAL_MODEL=gpt-oss-20b                   # optional; else GET /models decides
lobi --provider local "summarize this repo"
```

`capabilities` are probed from `GET {base}/models`, so the context window is the
served model's real `max_model_len` and not a guess. Unlike the other two
providers, `local` is never silently fallen back away from when a key is
missing: asking for the endpoint on this host and being answered by OpenAI is
the opposite of what was asked.

### Mission mode — the model chooses the tool

Everywhere else you choose the tool with a flag. That cannot work against a
server whose tools are discovered at runtime, so `--mission` puts the catalogue
in front of the model instead:

```bash
pip install 'judais-lobi[mission]'
lobi --mission --mcp-stdio 'python -m some_mcp_server' "what governed datasets exist?"
lobi --mission --mcp-url https://host/mcp   "..."   # bearer token in MCP_TOKEN
```

`[mission]`, not `[mcp]`. The narrower extra installs a *runnable* mission and a
silently **ungoverned** one: `--skill` reads YAML frontmatter, so with no
`pyyaml` the manifest never loads, the closed tool set is never applied and the
grounding check never runs — while the transcript looks exactly like a governed
one. Both halves, or neither.

Each tool a server advertises is registered into the existing `ToolBus` as a
`ToolDescriptor` whose executor dispatches `tools/call`, namespaced `mcp.<name>`
so a server cannot shadow a local tool. Capability gating, the panic switch and
the audit log apply to it exactly as to `fs` or `git`. The tool's JSON Schema is
carried whole on the descriptor, so the catalogue the model reads says
`type (string: dataset|model|service)` and not just `type` — types, `required`
and enums are what decide whether a first call to a faceted search works.

#### The mission-mode surface

These flags are a **contract**, not a convenience: `core/runtime/contract.py`
publishes them as `CLI_FLAGS`, a test asserts the parser takes every one, and a
program that spawns this harness may rely on them. The rest of `--help` is a
person's surface and may move.

| flag | env | what it does |
| --- | --- | --- |
| `--mission` | — | run as a mission rather than a chat turn |
| `--mcp-url` | `MCP_URL` | the tool plane, over streamable HTTP |
| `--mcp-stdio` | `MCP_STDIO` | a tool plane to spawn on this host, as a command line. One of the two, never both |
| `--mcp-token` | `MCP_TOKEN` | bearer token for `--mcp-url`. **Prefer the env var** — an argument is visible in `ps` |
| `--mission-steps` | — | hard cap on tool turns. Default **8**, and it counts parse-error turns too |
| `--mission-seconds` | `MISSION_SECONDS` | wall-clock cap on the whole run, in seconds. **Unset means unbounded** — steps bound the work, seconds bound the waiting, and a default nobody chose would kill a slow local model mid-answer. Checked between steps and before each model call; one clock for the whole of a `--swarm` turn. A call already in flight is not interrupted, so the real bound is this plus one round trip |
| `--provider` | — | `openai`, `mistral` or `local` |
| `--model` | — | which model on it |
| `--profile` | `JUDAIS_LOBI_PROFILE` | the capability profile: deny-by-default `safe`, then `dev`, `ops`, `god`. A refusal names the scope and the profile that grants it |
| `--unsandboxed` | `JUDAIS_LOBI_SANDBOX=none` | run tool subprocesses with no isolation. Without it, `bwrap` wherever bubblewrap exists; `JUDAIS_LOBI_SANDBOX=bwrap` forces it and refuses on a host without it |
| `--skill` | `MISSION_SKILL` | a `SKILL.md` manifest, or a directory holding one |
| `--swarm` | `MISSION_SWARM` | stage the mission when it needs staging |
| `--events` | `MISSION_EVENTS` | where the NDJSON account goes: `-`, `fd:N`, or a path |
| `--history` | `MISSION_HISTORY` | a JSON file of prior conversation turns |
| `--gate-tool` | — | a tool to offer and refuse to call. Repeatable |
| `--approval` | `MISSION_APPROVAL` | an approval id somebody already decided. Lifts that one tool out of the gated set, for this run only |
| `--temperature` | — | sampling. Unset sends **nothing** and the server's own default applies |
| `--top-p` | — | nucleus sampling. Unset sends nothing |
| `--seed` | — | a seed where the server honours one. Not a determinism guarantee |
| `--resume` | `MISSION_RESUME` | carry on a recorded mission by its run id. The objective comes off the record, so the message may be omitted |

The rest of the published environment: `MCP_CLIENT_NAME` is what this client
calls itself in the MCP `initialize` handshake — set it to the agent's name, or a
server that governs by principal records every call as an anonymous one, and
anything scoring the agent from the audit trail measures it as having called
nothing. `ELF_PERSONALITY` and `TAI_PERSONALITY` point at persona files;
`LOCAL_API_BASE` and `LOCAL_MODEL` aim the local backend. `JUDAIS_LOBI_AUDIT`
moves the audit file (a path) or silences it (`none`/`off`); either way
`mission_started.audit_ref` says which. `JUDAIS_LOBI_RUNS` does the same for
the durable transcript — a path moves the run directories, `none`/`off` keeps
none at all, and `mission_started.run_id` is present exactly when there is one
to name. `JUDAIS_LOBI_APPROVALS` does the same
for the durable approval records — a path moves the directory, `none`/`off`
keeps none, and then a gate stops a mission and leaves nothing anybody can
decide against, which the console says out loud. `MISSION_RESUME` is the environment form of
`--resume`.

### Resuming a mission — `--resume`

A run that was killed — the machine went down, somebody stopped the process,
the model server went away mid-step — left a numbered log behind. `--resume`
reads it back and carries on:

```bash
judais --mission --resume run_20260815T131102-9f3a1c04 \
       --mcp-stdio 'python -m some_mcp_server'
```

The objective comes off the recorded run, so the message is omitted; passing
one that is not the recorded objective is refused naming both, because a
resume of the wrong run looks exactly like a run continuing. So is an id the
store never minted, and so is a run that already finished — with one
exception: a run that ended `awaiting_approval` is waiting on a *person*, not
on this harness, and is resumable.

What comes back is the transcript's steps, the mission result store (its
handles keep addressing the same results), and the model's message list
rebuilt from the recorded `tool_call`/`tool_result` pairs and
`reply_rejected` problems. The records go on being appended to the **same**
run directory, and there is no second `mission_started` — a resumed run is
the same mission. The first new `step_started` carries
`resumed: {from_seq, steps_replayed}` instead.

`max_steps` counts the whole run: recorded steps included. Without
`--mission-steps` the resumed stretch is held to the total the run started
with, so killing and resuming cannot buy extra steps; with it, the number is
read as that many *further* steps.

Two things do not come back, and the harness says so on the console rather
than replaying in silence: the typed payload of a tool result
(`structuredContent` was never on the wire, so `mission_result(path=…)`
refuses a field path into a replayed result, though grounding still sees the
replayed text) and the text of a rejected reply (`reply_rejected` carries the
refusal — the reply is the thing that did not parse).

A staged (`--swarm`) mission checkpoints its plan and each step's outcome into
the run's `meta.json` as it goes, and **is refused** by `--resume` today: the
refusal names the steps that are done. Resuming it with the direct loop would
restart the plan rather than continue it.

Every mission also **reconciles orphans** on the way in: a run in the store
with no `mission_finished` whose metadata has not been touched for 60 seconds
gets one appended (`incomplete`), so a follower's stream closes and a reader
of `since()` is told the truth. The staleness is a guard, not an
optimisation — a mission thinking for forty seconds has no `mission_finished`
either, and closing its log out from under it would send the answer to nobody.
The credential is deliberately **not** persisted: `MCP_TOKEN` is read from the
environment of the resuming process, exactly as on a fresh run.

### A skill manifest — `--skill`

The harness owns mechanisms; whoever operates the platform owns content. A
`SKILL.md` is how the content arrives: YAML frontmatter plus a Markdown body,
the format Claude-style skills already use.

```bash
lobi --mission --skill ./skills/catalogue_recon/SKILL.md \
     --mcp-stdio 'python -m some_mcp_server' "what governed datasets exist?"
```

Three things come out of it, and nothing else does:

* **a closed tool set**, `allowed_tools`, intersected with what the bridge
  actually discovered. A bare name matches a namespaced one, so a manifest says
  `catalog_search_assets` and gets `mcp.catalog_search_assets`. A named tool the
  server does not offer is a **refusal listing every missing name** — never a
  silent narrowing, because a mission missing the tool that answers its question
  answers it from the model's memory instead and the transcript looks ordinary.
  Suffix an entry with `?` to mean "if the host offers it";
* **prompt text** — the operational frontmatter fields and the whole body,
  appended after the persona. Fields this loader has never heard of are rendered
  too: a manifest is content, and the harness is not the authority on which of a
  platform's operational fields matter;
* **a grounding grammar**, below. Optional; absent means nothing is enforced and
  nothing claims to have been.

One thing a manifest is *refused* for: **`sandbox: bwrap`, required the moment
`allowed_tools` names a tool that runs code the model composed** — a shell, an
interpreter, a `pip install` (the set is derived from the `shell.exec`,
`python.exec` and `pip.install` scopes in `core/tools/descriptors.py`, not from a
list of names, so a tool registered tomorrow is covered the day it arrives). A
governed mission that can run arbitrary code on the host without isolation is the
hazard here, and a hosted platform must not have to find it in a transcript. Both
halves are checked, and the refusal names every problem at once:

```yaml
allowed_tools: [governed_read, run_shell_command]
sandbox: bwrap          # or the resolve refuses, naming the tool and the fix
```

* the **declaration** is required of the manifest — including for an entry marked
  `?`, because whether a file is governed must not depend on what a server
  happened to advertise this morning;
* the **isolation** is required of the run: declare `sandbox: bwrap` and get a bus
  that is not under bwrap (not installed, or opted out) and the mission refuses at
  the door rather than running unisolated.

`sandbox: none` is the other legal value — an explicit *no isolation was asked
for*, accepted and inert for a manifest with no code-plane tool, and refused with
its own reason for one that has them. Absent is not `none`; absent is silence,
which is what this check exists to stop being an answer. The value is rendered
into the prompt like any other operational field, because a model that has not
been told it is inside bwrap reads the denied network as a broken tool.

### Bounded results, and a store to read the rest from

A tool result is capped at 32 KB before it enters the transcript — head and
tail with an explicit marker. The cap and the cut have one owner,
`core/bounding.py` (`MAX_RESULT_BYTES`, `bound_result`); the kernel's
`max_tool_output_bytes_in_context` and the chat path's are configuration knobs
that default to it, and every path that bounds a tool result calls the same
function. Uncapped, one large governed view evicts the earlier steps the model
needs to know what its numbers mean, or exceeds `max_model_len` outright, and
neither leaves a trace in the answer.

The whole result — including the `structuredContent` that `as_tuple()` drops
whenever there is text — stays in a per-mission store, and the marker names the
handle:

```
mission_result(handle="r1", path="result.actors[0].score")
```

A few dozen bytes instead of two hundred kilobytes. The store reaches nothing:
every byte in it already arrived through a gated, audited dispatch of a tool the
closed set allowed. It is registered on the bus for the length of one run and
withdrawn after it.

### Grounding — every identifier has to have come from a tool

`core/runtime/grounding.py` is the mission-tier analogue of `CompositeJudge`.
Every identifier-shaped token in the answer must appear in a tool output **of
this run**. An unsupported claim gets one repair turn naming the exact tokens;
a second failure keeps the answer and appends an explicit caveat, because
deleting it would hide a finding and passing it silently would launder one.

The grammar is not in the code. It comes from the manifest:

```yaml
grounding:
  identifier_pattern: '\b(?:asset|labels|run)\.[0-9a-f]{4,}\b'
  ignore: [asset.0000]
  max_repairs: 1
  must_cite: {identifiers: 1}     # optional; see below
```

No block, no validator, and the transcript's `grounding` stays `None` rather
than claiming a clean check. A check that could not run reports *no opinion* and
never a pass — same reason `LLMReviewTier` returns `UNKNOWN` instead of 0.5, and
a larger one here: a fabricated "grounded" is a governance claim.

**Three states, not two.** A check reports `unconfigured`,
`nothing_considered`, `supported` or `unsupported`. The third exists because the
second was being reported as a pass: on 10 August 2026, the first run with these
blocks switched on, six of the first ten missions reported `grounded:
identifiers — 0/0 supported by a tool result in this run`. The control was
satisfied by silence. `report.grounded` now means *nothing unsupported*;
`report.verified` means *and something was actually checked*, and the CLI prints
`NOTHING CHECKED` for the gap between them.

**A claim table, where the figures matter.** `claim_table: true` turns on a
third check. The skill's `output_format` asks for every figure a second time
beside the prose, as a path into what a tool returned:

````
```claims
[{"value": 0.7446, "path": "gate.confidence"},
 {"value": 338.0,  "path": "network.nodes[0].scores.out_weight"}]
```
````

Verification is then arithmetic rather than search: `results.walk_path` — the
same walker `mission_result` answers with — reads that path out of the payloads
the mission received and compares. A path that does not resolve, or resolves to
something else, is unsupported; an unreadable table is a finding rather than a
skip. The prose checks do not read the block, because a table full of
`gate.confidence` would otherwise be reported as invented identifiers.

**Whether silence is acceptable is the skill's call, not the harness's.**
`must_cite` is a minimum per check — `true` for every configured check, a list
of names, or `{claims: 3}` for a schema minimum. A skill whose answer may
legitimately be "the catalogue holds none of that" declares no minimum; a skill
drafting a finding declares one, and an answer with nothing in it fails. A
`must_cite` naming a check the same block does not configure is refused at
load: a requirement that never binds is the original hole wearing the name of
the fix for it.

### Gates — a tool offered, and not called

`--gate-tool NAME` (repeatable) names a tool this deployment offers **and
gates**. It is shown in the catalogue, marked. If the model names it, the call is
not made: the mission emits `gate_requested` carrying the proposed arguments
**verbatim** — what a person approves has to be the bytes that would run — and
ends at outcome `awaiting_approval`.

**No flag on a mission run answers a gate.** A harness that could approve its
own proposal has a gate that is a formality, and there is no code path in
`MissionRunner` or `SwarmRunner` that can move a record to *approved* — a test
greps for it.

What there *is* is the other half: the request is written down, and the answer
arrives from outside the run.

```
# the mission stops, and says what it stopped on
judais --mission --gate-tool mcp.cancel_job "wind down job j-91"
  ⏸️  Waiting on a person: Tai proposed mcp.cancel_job({'job': 'j-91'}) …
     approval ap_4b1f7c02e9d38a55 — decide it with: …

# somebody who is not this process decides
judais --mission --approve ap_4b1f7c02e9d38a55 --decided-by dana --note "queue is drained"

# and the work resumes, once
judais --mission --approval ap_4b1f7c02e9d38a55 --gate-tool mcp.cancel_job "wind down job j-91"
```

Each request is a JSON file under `.judais-lobi/approvals/` (moved or silenced
by `JUDAIS_LOBI_APPROVALS`) holding the tool, the arguments verbatim, the
objective and the run that asked; its id rides `gate_requested.approval_id`.
`--approve`/`--refuse` build no agent, ask no model and emit no events — they
call `ApprovalStore.decide` and exit — and they refuse a decision that names
nobody. `--decided-by` is free text: this framework has no principal system and
will not invent one, so *who counts as a person* is the platform's question; a
platform that knows the answer calls `core.runtime.approvals.ApprovalStore`
directly instead of these flags.

`--approval <id>` then widens the closed set by **exactly one tool, for exactly
one run, after exactly one person said so**, and the approval is spent the
moment that tool is dispatched — a run that never calls it leaves the decision
unspent rather than burning it on nothing. A pending, refused, spent or
abandoned record is refused at the door, naming the state: nothing defaults or
expires into a yes, and a spent approval is not a second one. A consumer reading
the stream sees the widening as that tool's **absence from
`mission_started.gated`**; there is no separate field announcing it.

`ApprovalStore.reconcile(live_run_ids)` marks pending requests whose run is gone
as `abandoned`, which is a *refusal*. It is provided and not yet wired to
startup: nothing in this repo can say which runs are alive until run durability
lands, and a liveness check that guessed would abandon live requests.

Name a gated tool the way the resolved catalogue names it: unlike
`allowed_tools`, gate names are matched by exact membership in the resolved set,
and bridged tools are namespaced (`mcp.cancel_job`, not `cancel_job`).

### `--swarm` — staged decomposition, when it is needed

A 20B model at 59 tok/s drowns in one long transcript. By step six of a single
mission the catalogue lookups that told it what its numbers mean have been pushed
out of attention by three governed views, and the answer is written from the part
it can still see. The fix is not a longer prompt; it is *shorter ones*.

`--swarm` (or `MISSION_SWARM`) puts five small roles over **the same backend and
the same tool bus**: triage, plan, execute, gate, synthesize. Triage is one cheap
call and is biased to running the ordinary loop — a swarm that makes "what's
trending" slower is a regression, so every failure of the router falls back to
DIRECT. Each executed step is its own small mission with a tight budget; earlier
steps arrive as short summaries, never as raw output. The closed tool set, the
gating, the audit and the events vocabulary are all exactly the direct path's, so
a watcher sees one mission with more steps.

Each planned step is tagged with a **rung** — `tool`, `code`, or `code+sdk`. The
last one is offered only when the skill manifest declares `sdk_import`, because
"import the platform SDK" with no SDK named is an invitation to invent a module
and a 20B accepts it.

### The mission stream — `--events`

`MissionRunner.run` returns a transcript when the mission is over. That is the
right shape for a terminal and the wrong shape for anything that has to *show* a
mission to somebody while it runs — a mission on a local 20B is minutes long, and
a caller holding only `run()` has nothing to render for all of them.

So the loop takes an observer, and `--events` writes what it sees as NDJSON: one
JSON object per line, flushed as it happens, UTF-8 and unescaped.

```
--events -        stdout, for a person with jq
--events fd:N     an inherited descriptor — what a harness uses
--events PATH     a file, opened for append
```

**stdout is prose for a person and must not be parsed.** The event sink is the
only machine channel, which is why a consumer uses `fd:` or a path and never `-`:
the console rendering and the record stream never share bytes.

The vocabulary — nine event types, their required and optional fields, the five
outcome words, the exit contract, and the rule for what is a breaking change —
is **[`CONTRACT.md`](CONTRACT.md)**, and its authority is
`core/runtime/contract.py`. A consumer pins it:

```python
from core.runtime import contract
assert contract.SCHEMA_VERSION == 1     # fails at import, which is cheap
problems = contract.conforms(record)    # [] when the record is fine
```

`conforms` is pure and standard-library only and imports nothing this repo owns,
so a consumer that cannot import an agent framework can vendor that one file and
have the whole seam.

### `--history` — a conversation, not a paragraph

`--history FILE` seeds prior turns into the model's message list as **real
role-tagged chat turns**, ahead of the objective. The file is a JSON array of
`{"role": "user"|"assistant", "content": "..."}`, oldest first; `system` is
refused, because system text belongs to the harness and tool turns are this
mission's own to make. Caps are 100 turns and 262,144 characters, and a malformed
history is a refusal at the door rather than a silent drop — a dropped history is
the bug this flag fixes wearing a different hat.

A file rather than an argument, for the same reason `--mcp-token` prefers the
environment: a conversation is many kilobytes and argv is world-readable in
`/proc/<pid>/cmdline`.

**A caller passing this must not also fold the history into the message.** A
chat-tuned model attends to role-tagged turns and skims past the same text pasted
into the objective: measured 12 August 2026, "tell me more about #2"
web-searched `#2` literally while the list sat two lines up in the prompt.

### Sampling — stated, or the server's own

`--temperature`, `--top-p` and `--seed` are unset by default, and unset means
**unsent**: the request carries no sampling parameters and the server's own
default applies. That is deliberate. Pinning `temperature=0` would make the agent
easier to measure by making it a different agent — it collapses the noise instead
of measuring it, and a noise floor taken at a temperature nobody ships is not a
floor. What was missing was never a temperature but the *ability to state one and
see what went out*; "server default" is a setting nobody chose, and an upgrade
can move it with nothing in any log. When one is passed, the CLI says so on the
console and the value is on the wire.

`--seed` is not a determinism guarantee. A batching server can still vary.

### A personality from a file

`--personality <path>` (or `TAI_PERSONALITY`, then `ELF_PERSONALITY`) loads a `PersonalityConfig` from
TOML, JSON or YAML. The keys are that model's fields and nothing else — an
unknown key is refused by name. JudAIs and Lobi are unaffected.

`tai` resolves its own file instead of being handed one: `$TAI_PERSONALITY`, then
`$ELF_PERSONALITY`, then the installed deployment package's own resource. Nothing
else is consulted and nothing is invented — the third outcome is a refusal naming
what was checked. A guess that lands on the wrong checkout is worse than no
guess, because it starts an agent whose stated rules are not the rules it loaded.

### For platforms

If you are wiring this framework into a platform — giving it a personality,
giving it capabilities as MCP tools and a skill manifest, driving it as a
subprocess and pinning a release — that is its own guide:
**[`PLATFORMS.md`](PLATFORMS.md)**. It covers the personality format and how to
add a new named agent, the `SKILL.md` fields including `sdk_import`, the exact
spawn shape, the release-and-pin loop, and the list of things that must never
enter this repository. TAIPAN is the worked example throughout.

## Extensibility

Judais-Lobi is designed to grow by adding workflows, tools, and policies without rewiring the kernel:

* Add a new workflow by defining a `WorkflowTemplate` in `core/kernel/workflows.py`.
* Add or consolidate tools via `core/tools/descriptors.py` and `core/tools/`.
* Define stricter safety boundaries with `core/policy/` profiles.
* Extend evaluation logic under `core/judge/` and `core/critic/`.

# 🚧 Current Status

**v0.9.0 — 2341 tests collected.** Mission mode, skill manifests, the grounding
validator, `--swarm`, the NDJSON mission stream and the published contract are
all in this release. 0.9.0 is **safe by default**: tool subprocesses run under
`bwrap` wherever bubblewrap exists (opt out with `--unsandboxed`, announced as
`sandbox` on `mission_started`), the capability profile is deny-by-default
`safe` (`--profile dev|ops|god` opts up and every refusal names the scope and
the profile that grants it), every default bus writes an append-only audit
file (`audit_ref`), a manifest that names a code-plane tool must declare
`sandbox: bwrap` and get it, and one redactor scrubs every error string that
reaches the stream. The kernel's role prompts are bounded by the same context
window the mission uses, and Phase 8 is closed. `CONTRACT.md` is the seam a consumer pins; `PLATFORMS.md` is
how a platform deploys this framework as its own agent.

`ROADMAP.md` is the one roadmap: §1 is where the framework stands at 0.9.0
and what is still missing, §2 is Phases 9–13, and §5 is the history — the
Feb 2026 blueprint, the Phase 8 disposition, and what two weeks in production
taught. `NEXT_STEPS.md` and `PHASE_8.md` were folded into it on 15 Aug 2026.

### Completed

The counts below are the suite totals **at the time each phase landed**, kept as
a record of how it grew. The current total is the one above.

* ✅ Phase 0 — Dependency Injection & Test Harness (73 tests)
* ✅ Phase 1 — Runtime extraction (provider separation, 107 tests)
* ✅ Phase 2 — Kernel State Machine & Hard Budgets (164 tests)
* ✅ Phase 3 — Session Artifacts, Contracts & KV Prefixing (269 tests)
* ✅ Phase 4 — Tool Bus, Sandboxing & Capability Gating (562 tests)
* ✅ Phase 5 — Repo Map & Context Compression (783 tests)
* ✅ Phase 6 — Repository-Native Patch Engine (888 tests)
* ✅ Phase 7.0 — Pluggable Workflows & State Machine Abstraction
* ✅ Phase 7.1-7.2 — Composite Judge & Candidate Sampling
* ✅ Phase 7.3 — External Critic
* ✅ Phase 7.4 — Campaign Orchestrator + StepPlan + EffectiveScope

### Up Next

Phase 8 closed at 0.9.0, and the numbering continues in `ROADMAP.md` §2:

* ⏳ Phase 9 — durable and bounded: a fsync'd append-only transcript, resume,
  a wall-clock budget, a usage ledger, approvals as durable records
* ⏳ Phase 10 — measurable: an in-repo eval harness scored from recorded runs
* ⏳ Phase 11 — one runtime: the mission loop and the kernel become one `Run`
* ⏳ Phase 12 — providers and streaming: `answer_delta` at the source
* ⏳ Phase 13 — embeddable: a library API first, the CLI second (1.0)

### Phase 7 Highlights (7.0–7.4)

Phase 7 turns the kernel into a workflow-driven, multi-candidate, multi-critic, campaign-capable system.

* **Pluggable workflows** — `WorkflowTemplate` makes phases, transitions, schemas, and capability profiles data-driven. `CODING_WORKFLOW` preserves Phase 6 behavior; `GENERIC_WORKFLOW` enables custom domains.
* **Deterministic scoring** — `CompositeJudge` sequences tests/lint/LLM review and scores candidate patches. `CandidateManager` evaluates N patch sets in isolated worktrees and picks the top non-failing result.
* **External Critic** — Optional frontier-model auditor (OpenAI/Anthropic/Google) for independent logic audits. Keyring/env key handling, multi-round feedback loop, noise detection, and SHA256 cache.
* **Campaign Orchestrator** — Tier‑0 mission layer with HITL approval gates, step DAG execution, artifact handoff, and resumable progress.
* **StepPlan + EffectiveScope** — Step-level contracts and SHA256 ActionDigest; tool access enforced by `Global ∩ Workflow ∩ Step ∩ Phase`.

Outcome: workflows are composable, evaluation is deterministic, critics are optional, and campaigns provide a macro loop for multi-step missions.

### Phase 6 Highlights

The agent can now reliably modify repository files through a deterministic, exact-match patch protocol with git worktree isolation and automatic rollback.

* **`core/patch/parser.py`** — Extracts `<<<< SEARCH / ==== / >>>> REPLACE`, `<<<< CREATE / >>>> CREATE`, and `<<<< DELETE >>>>` blocks from raw LLM text output. Delimiter-safe (only recognizes markers at line start). Path validation rejects absolute paths and `..` traversal at parse time.
* **`core/patch/matcher.py`** — Exact byte-match with byte offsets and SHA256 context hashes. On zero matches: 3-stage similarity narrowing pipeline (indent filter → token overlap → `SequenceMatcher` ratio) returns top 3 candidate regions. On multiple matches: returns all offsets + context hashes for LLM disambiguation.
* **`core/patch/applicator.py`** — File writes with strict preconditions. Path jailing (symlink-escape resistant). `\r\n → \n` canonicalization. `st_mode` preservation (executables stay executable). Create fails if file exists; delete fails if file doesn't exist.
* **`core/patch/worktree.py`** — `PatchWorktree` manages git worktree lifecycle: `create` (explicit `-b` + `HEAD`), `merge_back` (`--no-ff` + branch cleanup), `discard` (force remove + branch delete). Writes `.judais-lobi/worktrees/active.json` for crash recovery of orphaned worktrees.
* **`core/patch/engine.py`** — `PatchEngine` orchestrates validate → apply → diff → merge/rollback. Stops at first file failure, leaving worktree intact for diagnostics. `diff()` returns real `git diff` from the worktree.
* **`core/tools/patch_tool.py`** — ToolBus-compatible 6-action tool (validate, apply, diff, merge, rollback, status). All actions return JSON stdout for machine-friendly kernel orchestration. exit_code=0 only on success.

12 tool descriptors. 105 new tests (888 total). 3 integration tests with real git repos. Worktree isolation means cross-file patches land atomically — all succeed or discard for zero-cost rollback.

### Phase 5 Highlights

The agent is now repo-aware. It understands structure, relationships, and what's irrelevant — without eating the entire repo in context.

* **`core/context/repo_map.py`** — Top-level `RepoMap` orchestrator. Dual-use: overview mode (centrality-ranked for REPO_MAP phase) and focused mode (relevance-ranked by `target_files` for RETRIEVE phase). Lazy build with git-commit-keyed caching and dirty-file overlay.
* **`core/context/symbols/`** — 3-tier symbol extraction: Python `ast` (full import + signature extraction), tree-sitter (7 languages: C, C++, Rust, Go, JS, TS, Java), regex fallback. `get_extractor(language)` factory auto-selects the best available.
* **`core/context/graph.py`** — `DependencyGraph` with multi-language module resolution (Python dotted paths, C `#include`, Rust `use crate::`, Go package imports, JS/TS relative imports with extension guessing). Relevance ranking (1.0/0.8/0.6/0.4/0.1 scoring by hop distance) and centrality ranking with barrel file damping (`__init__.py`, `index.js`, `mod.rs`).
* **`core/context/formatter.py`** — Compact tree-style formatting with token budget, optional char cap, whitespace normalization for deterministic output, and metadata header (file/symbol counts, languages, ranking mode).
* **`core/context/visualize.py`** — DOT (Graphviz) and Mermaid graph export with highlight styling and node cap.
* **`core/context/cache.py`** — Git-commit-keyed persistent cache at `.judais-lobi/cache/repo_map/<hash>.json`. Clean commit = full cache hit; dirty state = cache + re-extract only modified files.
* **`core/tools/repo_map_tool.py`** — ToolBus-compatible multi-action tool (build, excerpt, status, visualize).
* **`setup.py`** — `pip install judais-lobi[treesitter]` adds optional tree-sitter support via individual grammar packages.

11 tool descriptors (now 12 with Phase 6). 221 new tests. tree-sitter is optional — the system works without it and gains rich multi-language AST parsing when installed.

### Phase 4 Highlights

Tools are dumb executors behind a capability-gated bus. The kernel decides everything.

* **`core/tools/bus.py`** — Action-aware `ToolBus` with preflight hooks, panic switch integration, and JSONL audit logging. Structured JSON denial errors replace plain text.
* **`core/tools/fs_tools.py`** — Consolidated `FsTool` with 5 actions (read, write, delete, list, stat). Pure `pathlib` I/O, no subprocess.
* **`core/tools/git_tools.py`** — Consolidated `GitTool` with 12 actions (status, diff, log, add, commit, branch, push, pull, fetch, stash, tag, reset) via `run_subprocess`.
* **`core/tools/verify_tools.py`** — Config-driven `VerifyTool` (lint, test, typecheck, format). Reads `.judais-lobi.yml` for project-specific commands, falls back to sensible defaults.
* **`core/tools/descriptors.py`** — 11 tool descriptors, 13 named scopes + wildcard. Per-action scope resolution via `action_scopes` map.
* **`core/tools/capability.py`** — Deny-by-default `CapabilityEngine` with wildcard `"*"` support, profile switching, and grant revocation.
* **`core/policy/profiles.py`** — Four cumulative profiles: `SAFE` (read-only) → `DEV` (+ write) → `OPS` (+ deploy/network) → `GOD` (wildcard).
* **`core/policy/god_mode.py`** — `GodModeSession` with TTL auto-downgrade, panic switch (instant revocation to SAFE), and full audit trail.
* **`core/policy/audit.py`** — Append-only JSONL `AuditLogger`, **attached to every `Tools()` bus by default**: one file per run at `.judais-lobi/audit/<run-id>.jsonl` under the working directory, named on the mission stream as `mission_started.audit_ref`, moved or silenced by `JUDAIS_LOBI_AUDIT=<path>|none|off` (silencing is announced, and travels as `audit_ref: null`). Every dispatch is a line — allowed, denied, panicked, unknown or thrown — with the redacted arguments, the decision and its reason, exit code, duration and bytes out. Redaction covers shapes (OpenAI, GitHub, AWS, Slack, `Bearer …`, `*_KEY`/`*_TOKEN`/`*_SECRET` assignments) *and* the values of the credential-named environment variables this process was given, because a token handed to a tool as an argument has no shape to match.
* **`core/runtime/resume.py`** — Picking a recorded mission back up, and closing the ones nobody will. Three separate things: the **door** (`open_for_resume` — an unknown id, a run that already finished, an objective that is not the recorded one, a staged run whose plan is checkpointed; every refusal answered before a server is dialled), the **replay** (`rebuild` — the recorded stream read back into the transcript's steps, the mission result store and the model's message list, rendering each replayed result through the runner's own `_render_result` so there is one owner of what a result reads like), and **reconciliation** (`reconcile_orphans` — a run with no `mission_finished` whose metadata has been untouched for `ORPHAN_STALE_S` gets one appended, so a follower's stream closes; the staleness rule is stated rather than assumed, because a mission that is merely thinking has no `mission_finished` either). What a replay cannot give back is written down as sentences (`LOST_*`) and shown, not swallowed.
* **`core/durable.py`** — The durability primitive, importing nothing else in this tree: `atomic_write_text`/`atomic_write_json` (tempfile in the same directory → flush → fsync → `os.replace`), `fsync_append`, and `RunStore` — one directory per run under `.judais-lobi/runs/<run-id>/` holding an fsync'd append-only `events.jsonl` of `{seq, at, record}` envelopes and a `meta.json` replaced atomically. Every record a mission emits is appended there before it reaches the `--events` sink, so the sink is a client of the log rather than a second copy; `since(cursor)` and `follow(cursor, stop=…)` are what a replay and a live subscriber read it back with. `seq` is monotonic per run and is persisted, and `RunStore.CALLER_OWNED` is why: writing a whole stale record back over a live one is how a reference platform came to reuse sequence numbers and show a blank transcript for a run whose records were on disk the whole time. `SessionManager` and `AuditLogger` are clients of this module, not second implementations of it.
* **`core/tools/sandbox.py`** — `NoneSandbox` (dev/debug) and `BwrapSandbox` (Tier-1 production) behind a common `SandboxRunner` interface. `BwrapSandbox` keeps every field of the `SandboxProfile` it is given: the host root read-only with the working directory (and `allowed_write_paths`) re-bound writable, a private tmpfs `/tmp`, the network namespace unshared unless the profile says `allow_network`, and `max_cpu_seconds` / `max_memory_bytes` / `max_processes` applied as rlimits on the bwrap process and inherited by what runs inside it. `NoneSandbox` is still the default; it enforces nothing and says so.

3 consolidated multi-action tools replaced 21 separate descriptors. Git is the spine, not nice-to-have.

---

# 🧭 Where To Look

If you are **running this from another program**, read:

* 📄 `CONTRACT.md` — the mission stream, its events and the exit contract
* 📄 `PLATFORMS.md` — deploying judais-lobi as a platform's agent

If you want to understand **where this is going**, read:

* 🗺️ `ROADMAP.md` — the only roadmap: where 0.9.0 stands (§1), Phases 9–13
  (§2), the principles (§3), and the Feb 2026 blueprint kept as history (§5)

If you want to understand the **current implementation**, inspect:

* `core/agent.py` — concrete Agent class (replaced `elf.py` in Phase 3)
* `core/runtime/contract.py` — the seam a consumer pins, as data
* `core/runtime/mission.py`, `mission_stream.py`, `swarm.py` — the mission loop, its NDJSON account, and staged decomposition
* `core/runtime/skills.py` — the `SKILL.md` loader: closed tool set, prompt, grounding grammar, `sdk_import`
* `core/contracts/` — Pydantic v2 contract models for all session data
* `core/sessions/` — SessionManager for disk artifact persistence
* `core/kernel/` — state machine, budgets, orchestrator, workflow templates (`workflows.py`)
* `core/cli.py`  — CLI interface layer
* `core/memory/memory.py`  — FAISS-backed long-term memory (numpy fallback if FAISS unavailable)
* `core/tools/` — ToolBus, capability engine, sandbox, consolidated tools (fs, git, verify, repo_map, patch)
* `core/policy/` — profiles, god mode, audit logging
* `core/context/` — repo map extraction, dependency graph, symbol extractors (Python ast + tree-sitter + regex), formatting, caching, visualization
* `core/patch/` — patch engine: parser, matcher, applicator, worktree manager, engine orchestrator
* `core/judge/` — composite judge: tier scoring, candidate sampling
* `lobi/`  and `judais/`  — personality configs extending Agent

If you want to understand the **entry point**, see:

* `main.py` 
* `setup.py` 

---

# 🏗 Architectural Direction

The target architecture (from the roadmap) is:

* Artifact-driven state (no conversational drift)
* Three-tier orchestration: Campaign graph (Tier 0) → Workflow graph (Tier 1) → Phase-internal planning (Tier 2)
* Pluggable workflows — static templates for coding, red teaming, data analysis, and arbitrary tasks
* Campaign orchestration — multi-step missions with DAG decomposition, HITL approval gates, and artifact handoff (pre-authored plans)
* Capability-gated tool execution with least-privilege by intersection (Global ∩ Workflow ∩ Step ∩ Phase)
* Sandbox isolation (bwrap / nsjail)
* Tests > Lint > LLM scoring hierarchy
* Endpoint-probed orchestration (vLLM / TRT-LLM serve the model; the client asks the endpoint how big its window is)
* Optional external critic (frontier logic auditor)

The system is moving toward:

```
CLI (--task / --campaign / --campaign-plan / --workflow)
  ↓
Campaign Orchestrator (Tier 0 — optional, multi-step missions)
  ↓  plan → HITL approve → dispatch → synthesis
Workflow Selector → WorkflowTemplate (Tier 1 — static graph)
  ↓
Kernel State Machine (phases, transitions, budgets)
  ↓
Roles (Planner / Coder / Reviewer)
  ↓
ToolBus → EffectiveScope check → Sandbox → Subprocess
  ↓
Deterministic Judge (Tests > Lint > LLM)
```

As of Phase 7.4:

* The kernel state machine is parameterized by `WorkflowTemplate` objects — no hardcoded phase names, transitions, or branching rules. The coding pipeline is one template; custom domains define their own.
* `CODING_WORKFLOW` and `GENERIC_WORKFLOW` are built-in templates. `select_workflow()` resolves by CLI flag, policy, or default.
* Per-phase capability profiles (`phase_capabilities`) create temporal sandboxes — PLAN can read but not write, PATCH can write but only through the patch engine.
* Tools are dumb executors behind a sandboxed, capability-gated bus.
* Every **subprocess-based** tool call flows through `ToolBus → CapabilityEngine → SandboxRunner → Subprocess`. Pure-Python tools are still gated by ToolBus but execute in-process. `HUMAN_REVIEW` uses `$EDITOR` directly (user-initiated TTY) and is an explicit exception.
* Deny-by-default. No scope = no execution.
* God mode exists for emergencies — TTL-limited, panic-revocable, fully audited.
* 5 consolidated multi-action tools (fs, git, verify, repo_map, patch) cover 31 operations under 13 scopes.
* The agent sees repo structure via a token-budgeted excerpt — file paths, symbol signatures, and dependency-ranked relevance — without loading full source.
* 3-tier symbol extraction: Python `ast` → tree-sitter (7 languages) → regex fallback. Multi-language dependency graph with import resolution.
* Code modifications use an exact-match patch protocol with git worktree isolation. Cross-file changes land atomically. Failed patches roll back at zero cost.
* Patches are scored by a deterministic `CompositeJudge` (Tests > Lint > LLM review). `CandidateManager` evaluates N candidate patches in isolated worktrees and selects the winner by composite score.
* **Campaign Orchestrator** provides a Tier 0 macro loop with HITL approval, step DAG execution, and explicit artifact handoff.
* **StepPlan contracts** lock intent, boundaries, and capability needs per step with a SHA256 ActionDigest.
* **EffectiveScope intersection** (`Global ∩ Workflow ∩ Step ∩ Phase`) is enforced per tool call.
* **Context window manager** keeps prompts within model limits, auto-compacts history, and stores oversized tool output to disk with a retrieval hint.

Local inference has landed (`--provider local`), and Phase 8 closed at 0.9.0 — `ROADMAP.md` §5.10 records where each of its milestones ended up.

The kernel is the only intelligence. Tools report. The kernel decides.

---

# 🧠 Memory System (Current)

Long-term memory uses:

* SQLite-backed JSON persistence
* FAISS vector index (numpy fallback when FAISS is unavailable)
* OpenAI embeddings (currently)

See: `core/memory/memory.py` 

This will be abstracted for local embeddings in later phases.

Short-term history remains for direct chat mode. Direct CLI tool calls still route through ToolBus (with a permissive default policy unless a policy pack is supplied).
Agentic mode uses session artifacts as the sole source of truth (Phase 3).

---

# 🧰 Context Window & Tool Output

Judais-Lobi tracks context window limits per model/provider, auto-compacts history when needed, and never drops oversized tool output. Full logs are written to disk with a retrieval hint in the prompt.

Config (project-level) in `.judais-lobi.yml`:

```yaml
context:
  max_context_tokens: 32768
  max_output_tokens: 4096
  max_tool_output_bytes_in_context: 32768
  min_tail_messages: 6
  max_summary_chars: 2400
  provider_defaults:
    openai: 128000
    mistral: 32768
    local: 32768
  model_overrides:
    gpt-4o: 128000
    codestral-latest: 32768
```

---

# 🧮 Usage ledger

Every backend reports what the provider said a completion cost — `prompt_tokens`,
`completion_tokens`, `total_tokens`, plus any extras that provider sent, read off
`UnifiedClient.last_usage`. A mission accumulates them and finishes with a line:

```
🧮 usage: 8412 prompt + 903 completion tokens over 11 calls
```

On the event stream the same numbers ride `tool_call`, `answer` and
`reply_rejected` per call, and `mission_finished` as the run's totals. They are
**reported, never estimated**, and **absent rather than zero** when a provider
said nothing — which local endpoints often do. See `CONTRACT.md`.

Cost is optional and comes from configuration, never from a price list in this
repo — prices move and differ per account. Add a `pricing:` block to
`.judais-lobi.yml` and the totals grow a `cost`:

```yaml
pricing:
  openai:
    gpt-4o-mini: {prompt_per_1k: 0.15, completion_per_1k: 0.6}
    "*":         {prompt_per_1k: 1.0,  completion_per_1k: 2.0, currency: USD}
  local:
    my-served-model: {prompt_per_1k: 0.002, completion_per_1k: 0.002, currency: EUR}
```

`"*"` under a provider covers whatever else it serves. No block means tokens and
no cost, and `local` has no cost until somebody prices it.

---

# 🛠 Current Capabilities

Direct mode still works.

```bash
lobi "explain this function"
lobi --shell "list files"
lobi --python "plot sine wave"
lobi --search "latest linux kernel"
lobi --research "linux kernel LTS release timeline"
lobi --research --academic "transformer sparsity survey 2023"
lobi --install-project
```

JudAIs:

```bash
judais "analyze this target" --shell
```

Voice (optional extra):

```bash
pip install judais-lobi[voice]
lobi "sing" --voice
```

---

# 🧪 Install

```bash
pip install judais-lobi                 # the base install
pip install -e '.[mission]'             # from a checkout, with everything a mission needs
```

Requires:

* Python 3.10+ (`setup.py`'s floor; a TOML personality on 3.10 also needs `tomli`)
* A model to talk to: an API key for a hosted provider, or an OpenAI-compatible
  endpoint for `--provider local`
* Linux recommended

Every optional stack is an **extra**, not a requirement — a plain install stays
small enough that `judais --help` works without any of them, and the SDK an extra
pulls in is imported lazily.

| extra | what it adds |
| --- | --- |
| `mission` | `mcp` + `pyyaml` — what a governed mission actually needs. **This is the one a platform installs** |
| `mcp` | the MCP client alone. Enough to run a mission, not enough to govern one |
| `critic` | the external frontier-model critic, and `pyyaml` |
| `treesitter` | multi-language symbol extraction for the repo map |
| `faiss` | the FAISS vector index for long-term memory. Without it memory still works, on the numpy index in `core/memory/memory.py` |
| `voice` | TTS |
| `dev` | pytest and coverage |

Set an API key:

```bash
export OPENAI_API_KEY=sk-...
```

Or create:

```
~/.elf_env
```

---

# 🔐 API Keys & Model APIs

Judais-Lobi uses API keys from your environment or your system keyring. Keys are never stored in config files.

Environment variables (fallbacks):

* `OPENAI_API_KEY` — OpenAI (builder + optional critic)
* `ANTHROPIC_API_KEY` — Anthropic critic (optional)
* `GOOGLE_API_KEY` — Google/Gemini critic (optional)

Keyring (preferred, optional):

* Service: `judais-lobi`
* Keys: `openai_api_key`, `anthropic_api_key`, `google_api_key`

Model API configuration (critic only):

* User defaults: `~/.judais-lobi/critic.yml`
* Project overrides: `.judais-lobi.yml` under `critic:`

Example `critic.yml`:

```yaml
enabled: true
providers:
  - provider: openai
    model: gpt-4o
  - provider: anthropic
    model: claude-sonnet-4-20250514
```

---

# 🔮 What This Is Becoming

Judais-Lobi is not trying to be:

* Another chat wrapper
* Another SaaS IDE
* Another prompt toy

It is attempting to become:

* A local-first agentic execution kernel (not just developer — any structured task domain)
* Deterministic and replayable
* Hardware-aware
* Capability-constrained (least-privilege by intersection)
* Mission-capable (campaign orchestration with HITL approval gates)
* Air-gap ready

The design philosophy is explicit in `ROADMAP.md` §3:

* Artifacts over chat
* Budgets over infinite loops
* Capabilities over trust
* Capabilities over tools (stable tags, not tool names)
* Plans over prompts (structured DAGs, not freestyle LLM loops)
* Static graphs, adaptive phases (three-tier orchestration)
* Dumb tools, smart kernel
* Commit or abort

That last one matters.

There will not be two systems of truth.

---

# 🧠 Philosophy

Lobi sings.
JudAIs calculates.

But the system beneath them is becoming something else:

A disciplined orchestration engine for machine reasoning.

The aesthetic may be mythic.
The architecture is not.

---

# ⭐ Contributing

If you are contributing:

1. Read the roadmap.
2. Understand the phase ordering.
3. Do not bypass tool execution through direct subprocess calls.
4. Every structural change must preserve deterministic replay.
5. New functionality goes through `Agent` + contracts, not ad-hoc methods.

This is an architectural project, not a feature factory.

---

# 🧾 License

GPLv3 — see LICENSE.
