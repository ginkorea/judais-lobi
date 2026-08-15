# 🧠 judais-lobi

> Artifact-driven. Capability-gated. GPU-aware.
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
4. Use tools explicitly:
   `lobi --shell "ls -la"`

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
| `--provider` | — | `openai`, `mistral` or `local` |
| `--model` | — | which model on it |
| `--skill` | `MISSION_SKILL` | a `SKILL.md` manifest, or a directory holding one |
| `--swarm` | `MISSION_SWARM` | stage the mission when it needs staging |
| `--events` | `MISSION_EVENTS` | where the NDJSON account goes: `-`, `fd:N`, or a path |
| `--history` | `MISSION_HISTORY` | a JSON file of prior conversation turns |
| `--gate-tool` | — | a tool to offer and refuse to call. Repeatable |
| `--temperature` | — | sampling. Unset sends **nothing** and the server's own default applies |
| `--top-p` | — | nucleus sampling. Unset sends nothing |
| `--seed` | — | a seed where the server honours one. Not a determinism guarantee |

The rest of the published environment: `MCP_CLIENT_NAME` is what this client
calls itself in the MCP `initialize` handshake — set it to the agent's name, or a
server that governs by principal records every call as an anonymous one, and
anything scoring the agent from the audit trail measures it as having called
nothing. `ELF_PERSONALITY` and `TAI_PERSONALITY` point at persona files;
`LOCAL_API_BASE` and `LOCAL_MODEL` aim the local backend.

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

### Bounded results, and a store to read the rest from

A tool result is capped at 32 KB (`MAX_RESULT_BYTES`, the kernel's own
`max_tool_output_bytes_in_context`) before it enters the transcript — head and
tail with an explicit marker. Uncapped, one large governed view evicts the
earlier steps the model needs to know what its numbers mean, or exceeds
`max_model_len` outright, and neither leaves a trace in the answer.

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

**There is deliberately no flag that answers a gate.** A harness that could
approve its own proposal has a gate that is a formality. Whoever is driving the
mission resumes by spawning a new one with that tool dropped from its
`--gate-tool` list, which widens the closed set by exactly one tool, for exactly
one turn, after exactly one person said so.

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

`--personality <path>` (or `ELF_PERSONALITY`) loads a `PersonalityConfig` from
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

**v0.8.0 — 1782 tests collected.** Mission mode, skill manifests, the grounding
validator, `--swarm`, the NDJSON mission stream and the published contract are
all in this release. `CONTRACT.md` is the seam a consumer pins; `PLATFORMS.md` is
how a platform deploys this framework as its own agent.

`ROADMAP.md` and `PHASE_8.md` are historical (Feb 2026): they describe the plan,
not the code that is here now.

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

* ✅ Phase 8a — Local inference, a real MCP client, and file-loaded personalities
* ⏳ Phase 8b — Retrieval & context discipline

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
* **`core/policy/audit.py`** — Append-only JSONL `AuditLogger` with regex-based secret redaction (OpenAI, GitHub, AWS, Slack tokens).
* **`core/tools/sandbox.py`** — `NoneSandbox` (dev/debug) and `BwrapSandbox` (Tier-1 production) behind a common `SandboxRunner` interface.

3 consolidated multi-action tools replaced 21 separate descriptors. Git is the spine, not nice-to-have.

---

# 🧭 Where To Look

If you are **running this from another program**, read:

* 📄 `CONTRACT.md` — the mission stream, its events and the exit contract
* 📄 `PLATFORMS.md` — deploying judais-lobi as a platform's agent

If you want to understand the **plan it grew from**, read:

* 📜 `ROADMAP.md` — the Feb 2026 architectural blueprint. Historical

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
* `core/judge/` — composite judge: tier scoring, candidate sampling, GPU profile stub
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
* GPU-aware orchestration (vLLM / TRT-LLM)
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

Local inference has landed (`--provider local`). Phase 8b focuses on retrieval discipline. See `ROADMAP.md`.

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

The design philosophy is explicit in `ROADMAP.md` :

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
