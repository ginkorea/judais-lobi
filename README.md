# judais-lobi

[![PyPI](https://img.shields.io/pypi/v/judais-lobi?color=blue&label=PyPI)](https://pypi.org/project/judais-lobi/)
[![Python](https://img.shields.io/pypi/pyversions/judais-lobi.svg)](https://pypi.org/project/judais-lobi/)
[![License](https://img.shields.io/github/license/ginkorea/judais-lobi)](https://github.com/ginkorea/judais-lobi/blob/main/LICENSE)

**judais-lobi is a governed, local-first mission runtime for LLM agents.**
Tool subprocesses run sandboxed by default (`bwrap` wherever it is
installed); capability profiles are deny-by-default, so a mission gets only
the scopes it was granted; every dispatch through the default tool bus is
written to an append-only audit file; every run leaves a durable, numbered
log you can kill and pick back up with `--resume`, or run again with no
model at all through `--replay`; every claim in an answer has to trace back
to a tool result — a figure a program did not print is not in the draft; a
supervisor watches for a run going in circles instead of cutting it off at a
step count nobody chose; an eval harness scores a change from recorded
streams, with no GPU required to reproduce the score; three first-party
mission packs ship in the wheel; a memory bank, campaigns of missions, and
the built-in tools served back out over MCP are all in the tree. The whole
of it is a library API six objects wide and a wire contract a platform can
pin — `from judais_lobi import Run` is the same loop `judais --mission`
runs.

Two personalities ship on top of that runtime — 🧝 **Lobi**, a general
assistant, and 🧠 **JudAIs**, its sharper twin — plus **`tai`**, the mission
personality a deployment supplies its own persona file for. All three take
the same flags; only the character differs.

Distributed as `judais-lobi` on PyPI. `--provider local` against any
OpenAI-compatible endpoint (vLLM, llama.cpp, LM Studio, Ollama's `/v1` shim)
is the first-class target; `openai`, `anthropic` and `mistral` are the
hosted alternatives. Python 3.10+.

---

## Install, and your first mission

```bash
pip install 'judais-lobi[mission]'
```

`[mission]` — not the bare package, not `[mcp]` — is what a governed mission
needs: the MCP client, a YAML reader for `--skill`, and a JSON-schema
validator for tool arguments. Without it a mission still *runs*, silently
**ungoverned**: `--skill` reads YAML frontmatter, so with no `pyyaml` the
manifest never loads, the closed tool set is never applied and the
grounding check never runs, while the transcript looks exactly like a
governed one. Both halves, or neither.

Set a key for a hosted provider —

```bash
export OPENAI_API_KEY=sk-...        # or ANTHROPIC_API_KEY, or MISTRAL_API_KEY
```

— or point at a local server instead:

```bash
export LOCAL_API_BASE=http://127.0.0.1:8000/v1   # note the /v1
export LOCAL_MODEL=gpt-oss-20b                    # optional; else GET /models decides
```

Three commands install, one per personality; all three take `--provider
local|openai|anthropic|mistral` and everything below.

| command | personality |
| --- | --- |
| `lobi` | the general assistant, whimsical register |
| `judais` | the general assistant, ruthless register |
| `tai` | the mission personality — governed tools only, cites every claim, never sees source. Resolves its own persona file (`TAI_PERSONALITY`, then `ELF_PERSONALITY`, then the deployment package's own resource) or refuses, naming what it checked |

`python main.py [lobi|judais|tai] <message> [flags]` reaches the same three
from a checkout with nothing installed.

Now run a mission. Each first-party pack ships its own fixture data, staged
into a scratch directory so the mission has something real to read:

```bash
python -c "import core.skills as s; s.load('analyst').stage_fixtures('/tmp/analyst-demo')"
cd /tmp/analyst-demo
judais --mission --skill analyst --profile dev \
       "Something looks wrong in sales.csv — which orders do not belong?"
```

`research` needs no key, no browser and no search engine to answer from a
page you give it, under the `research` profile (`dev` plus `http.read`,
nothing more):

```bash
judais --mission --skill research --profile research \
       "What did the solar array generate in 2025? http://example.org/report"
```

`coding` runs against a real git repository — its own working directory —
and proves a change by running the repository's tests:

```bash
cd /path/to/your/repository
judais --mission --skill coding --profile dev \
       "Add a --colour flag and cover it."
```

What the console shows as a mission runs: `🧾 audit: …` and `🧾 run: …`
name where the audit file and the durable transcript live (or say they were
turned off); `🧱 sandbox: bwrap` or `🔓 sandbox: none` says whether tool
subprocesses are isolated; each tool call and result prints as it happens;
`🔎 grounded` (or `UNGROUNDED`, or `NOTHING CHECKED` when the manifest
configured no grounding grammar) reports the validator's verdict before the
answer; `🧞 <name>: …` is the finished answer; `⏸️  Waiting on a person: …`
is a gate standing open, with the exact command that decides it. None of
this is a machine channel — pipe `--events fd:N` or `--events PATH`
somewhere that reads NDJSON for that (see [the mission
stream](#the-mission-stream-in-brief), below).

### Every optional stack is an extra

A plain `pip install judais-lobi` keeps `judais --help` working with none of
them; the SDK an extra pulls in is imported lazily, so installing one you
never use costs nothing at runtime.

| extra | what it adds | install it when |
| --- | --- | --- |
| `mission` | `mcp`, `pyyaml`, `jsonschema` | **always, to run a mission** — this is the one a platform installs |
| `mcp` | `mcp` alone | you want the tool bridge and nothing else (the trap above) |
| `anthropic` | the Anthropic SDK | `--provider anthropic` |
| `critic` | Anthropic + Google SDKs, `keyring`, `pyyaml` | a manifest turns `grounding: critic: true` on and wants a hosted second opinion |
| `server` | starlette + uvicorn | you want to follow a run over HTTP (`python -m core.server`) instead of a pipe |
| `treesitter` | tree-sitter + seven grammars | the repo map should parse C, C++, Rust, Go, JS, TS or Java rather than fall back to regex |
| `faiss` | `faiss-cpu` | long-term chat memory is big enough for the vector index to matter (a numpy fallback is always there) |
| `voice` | TTS, torch, audio | the agent should speak |
| `dev` | pytest, coverage | you are running the suite |

Requires Python 3.10+ (`setup.py`'s floor — a TOML personality on 3.10 also
needs `tomli`, pulled in automatically) and Linux is recommended for the
sandbox.

---

## What ships at 1.0

| it | lives in | reach it with |
| --- | --- | --- |
| sandboxed tool execution (`bwrap`) | `core/tools/sandbox.py` | on by default; `--unsandboxed` / `JUDAIS_LOBI_SANDBOX=none` opts out |
| deny-by-default capability profiles | `core/policy/profiles.py` | `--profile` / `JUDAIS_LOBI_PROFILE` |
| per-run scope widening | `core/runtime/run.py` | `--grant` |
| an append-only audit file on every default bus | `core/policy/audit.py` | `JUDAIS_LOBI_AUDIT` |
| a durable, resumable run log | `core/durable.py` | `--resume` / `MISSION_RESUME` |
| recorded-run replay, no model | `core/runtime/replay.py` | `--replay` / `MISSION_REPLAY` |
| receipts-grounding on every claim | `core/runtime/grounding.py` | a manifest's `grounding:` block |
| a supervisor instead of a step budget | `core/runtime/supervisor.py` | on by default; `Bounds(supervisor=NO_SUPERVISOR)` opts out |
| a human gate as a durable record | `core/runtime/approvals.py` | `--gate-tool`, `--approval` / `MISSION_APPROVAL` |
| a reproducible eval harness | `core/eval/` | `python -m core.eval check|run|score|measure` |
| three first-party mission packs | `core/skills/library/` | `--skill analyst|research|coding` |
| a memory bank | `core/memory/bank.py` | `JUDAIS_LOBI_MEMORY` |
| campaigns — a plan of missions | `core/runtime/campaign.py` | `--campaign` / `--campaign-plan` |
| the built-in tools served over MCP | `core/tools/serve.py` | `python -m core.tools.serve` |
| the run store followed over HTTP | `core/server/` | `python -m core.server` (`[server]` extra) |
| a library API | `judais_lobi.py` | `from judais_lobi import Run` |
| a wire contract a platform pins | `core/runtime/contract.py` | [`CONTRACT.md`](CONTRACT.md) |

### The three packs

A manifest is content, not mechanism: `--skill` reads a `SKILL.md` — YAML
frontmatter plus a Markdown body — that closes the tool set, states a
grounding grammar and nothing else. Three ship inside the wheel, so a
`pip install` runs a governed mission with a real skill and no files of
your own:

| pack | what it does | closed set | profile |
| --- | --- | --- | --- |
| `analyst` | answers a question about local data files (CSV, JSON, JSON lines, logs) by computing it in sandboxed Python and reporting the figures the program printed | `run_python_code`, `fs` | `dev`, `sandbox: bwrap` |
| `research` | reads pages on the open web and answers with a URL beside every claim; a page it could not read is named with its status rather than filled in | `fetch_page_content`, `perform_web_research`, `perform_web_search?`, `fs?` | `research` |
| `coding` | changes a repository and proves it: maps it, edits across files in one patch, runs the repository's own tests, reports the counts the tests printed | `repo_map`, `fs`, `patch`, `verify`, `git`, `run_shell_command?` | `dev`, `sandbox: bwrap` |

Run one by name — no path, no file of your own — and `--skill` still takes
a path too: a path that exists wins, so every command line written before
packs existed does exactly what it did.

`coding` is the one that answers "this was not meant to just be a chat
agent." It runs where you are — the working directory is the repository —
and it is the pack whose manifest *requires* isolation, because its closed
set permits a shell on this host. It ships four small git-able repositories
under `fixtures/` and eight missions over them: a feature needing two
modules and a test, a bug whose fix is in two files, a rename with three
call sites, a flag that is never only a flag, a red suite that has to go
green with both counts reported, an agent that claims a pass it never
measured, and an objective that asks it to edit outside the repository.
Seventeen recorded streams under `tests/fixtures/eval/coding/` are real runs
of the real loop, real bwrap and a real `pytest`, with only the model
scripted.

A pack is a directory, `core/skills/library/<name>/`, and it is more than a
manifest (`ROADMAP.md` §2.6b):

```
core/skills/library/analyst/
    SKILL.md        the manifest — closed set, policy, grounding grammar
    missions.yaml   its OWN eval suite, in core/eval's shape
    README.md       what it does, its closed set, the profile it needs
    fixtures/       small committed data the missions run against
    templates/      task templates a campaign step can name
```

`missions.yaml` is what makes "tested" mean a number and not a paragraph:
every pack ships its own missions, one per capability, scored by
`core/eval` off the recorded stream.

```python
import core.skills
core.skills.packs()               # ('analyst', 'coding', 'research')
pack = core.skills.load("analyst")
pack.manifest.allowed_tools       # ('run_python_code', 'fs')
pack.suite()                      # its missions, checked
pack.stage_fixtures("/tmp/data")  # a COPY — a sandboxed run's cwd is writable
```

Each pack's own `README.md` — `core/skills/library/<name>/README.md` — is
the detail: what it refuses, why it needs the profile it needs, what its
fixtures hold, and what a live run against it found.

---

## How it is governed

**Capability profiles are deny-by-default.** Five, cumulative: `safe`
(read-only — the default), `dev` (+ write, shell, Python), `research` (`dev`
plus `http.read` and nothing else — carved out of `ops` because reading
three public pages used to cost a deploy right), `ops` (+ `git push`,
`pip install`, deletion), `god` (wildcard). `--profile` or
`JUDAIS_LOBI_PROFILE` opts a run up; a refusal always names the missing
scope and the lowest profile that grants it, for example:

```
denied under profile 'safe': python.exec needs --profile dev
(or JUDAIS_LOBI_PROFILE=dev)
```

`--grant` pre-authorises capability scopes for **this run only**, beyond
whatever `--profile` grants — `--grant http.read` lets a `safe` mission
fetch one page without opting the whole run up to `ops`, which would also
hand it `git.push`, `pip.install` and `fs.delete`. It widens scopes only:
the sandbox, the gated set and a skill's closed set are unchanged, and `*`
is refused outright, because that is `--profile god` by another name.
Arrives back on the stream as `mission_started.granted`.

**A skill manifest closes the tool set further still.** `allowed_tools`, in
`SKILL.md`, is intersected with what the bus actually discovered; a named
tool the plane does not offer is a refusal listing every missing name —
never a silent narrowing, because a mission quietly missing the tool that
answers its question answers it from the model's memory instead, and the
transcript looks ordinary. A manifest naming a **code-plane** tool — a
shell, an interpreter, `pip install` (derived from the `shell.exec`,
`python.exec` and `pip.install` scopes, not a list of names) — must declare
`sandbox: bwrap`, and the run must actually have it, or the mission refuses
at the door rather than running a model's own code on the host unisolated.

**The sandbox.** Tool subprocesses run inside `bwrap` wherever bubblewrap is
on `PATH`: the host filesystem read-only, the working directory (and
`allowed_write_paths`) re-bound writable, a private tmpfs `/tmp`, the
network namespace unshared unless a tool asks, CPU/memory/process rlimits
applied. `--unsandboxed` (or `JUDAIS_LOBI_SANDBOX=none`) opts out
explicitly; `JUDAIS_LOBI_SANDBOX=bwrap` forces it and refuses on a host
without it. Whichever happened rides `mission_started.sandbox`. **In-process
tools are rooted too**: `fs`, `patch`, `git` and `repo_map` are plain
`pathlib` in this interpreter — bwrap isolates a subprocess and never sees
them — so a mission carries a **root**, its working directory
(`core/tools/root.py`), and a path resolving outside it (absolute, `..`, a
symlink) comes back as an ordinary refusing tool result rather than a write
anywhere the user can reach. Chat is unrooted, as it always was.

**The audit file.** Every default `Tools()` bus writes an append-only,
secret-redacted JSONL log — one file per run, `allowed`/`denied`/
`unknown_tool`/`error`, with the decision, its reason, exit code, duration
and bytes out. `JUDAIS_LOBI_AUDIT` moves it (a path) or silences it
(`none`/`off`), and either way `mission_started.audit_ref` says which.
Redaction (`core/redact.py`) covers known credential shapes (OpenAI,
GitHub, AWS, Slack, `Bearer …`, `*_KEY`/`*_TOKEN`/`*_SECRET` assignments)
*and* the values of credential-named environment variables this process was
handed — a token passed to a tool as a plain argument has no shape to
match. One redactor, at the emitter, scrubs every free-text field that
reaches the stream or stderr.

**A gate is a tool offered and not called.** `--gate-tool NAME` (repeatable)
marks a tool in the catalogue; if the model names it, the call is not made —
the mission emits `gate_requested` with the proposed arguments **verbatim**
and ends at `awaiting_approval`. No flag on a mission run can approve its
own proposal — there is no code path in the runner that moves a record to
*approved*, and a test greps for it. The answer comes from outside the
process:

```bash
judais --mission --gate-tool mcp.cancel_job "wind down job j-91"
  # ⏸️  Waiting on a person: … approval ap_4b1f7c02e9d38a55 — decide it with: …

judais --mission --approve ap_4b1f7c02e9d38a55 --decided-by dana --note "queue is drained"

judais --mission --approval ap_4b1f7c02e9d38a55 --gate-tool mcp.cancel_job "wind down job j-91"
```

Each request is a JSON file under `.judais-lobi/approvals/` (moved or
silenced by `JUDAIS_LOBI_APPROVALS`) holding the tool, the arguments, the
objective and the run that asked. `--approval <id>` widens the closed set by
**exactly one tool, for exactly one run, after exactly one person said so**,
and is spent the moment that tool is dispatched. `--decided-by` is free
text — this framework has no principal system and will not invent one — but
a decision signed by nobody is refused. `ApprovalStore.reconcile` marks a
pending request whose run is gone as `abandoned`, run automatically on the
way into every mission, and announced when it finds anything to abandon.

---

## How it stays honest

**If a number is not in the view, it is not in the draft.** That sentence
sits in every mission's system turn (`core/runtime/prompts.py`), and
`core/runtime/grounding.py` is the machinery that makes it true whether the
model cooperates or not. Every identifier-shaped token in the answer must
appear in a tool output *of this run*; an unsupported claim gets one repair
turn naming the exact tokens, and a second failure keeps the answer with an
explicit caveat rather than deleting the finding or laundering it through
silence.

The grammar is declared, not built in — a manifest's `grounding:` block:

```yaml
grounding:
  identifier_pattern: '\b(?:asset|labels|run)\.[0-9a-f]{4,}\b'
  max_repairs: 1
  figures_from: [verify]      # which tool MEASURED the quantity; unset = every result grounds a figure
  must_cite: {identifiers: 1} # optional: a minimum per check
```

No block, no validator — the report stays `None` rather than claiming a
clean check. **Three states, not two**: `unconfigured`, `nothing_considered`,
or a verdict of `supported`/`unsupported`. `report.grounded` means *nothing
unsupported*; `report.verified` means *and something was actually checked*;
the console prints `NOTHING CHECKED` for the gap between the two, because a
check that ran over zero claims is not a pass.

Four ways a figure used to arrive ungrounded despite looking checked, all
closed mechanically: the **echo** (a model told a figure is unsupported can
print it back and re-submit — a code-plane call whose output holds no
figure it was not already given grounds nothing); the **clock** (a
timestamp donates digits to the evidence set unless timestamp-shaped spans
are masked on both sides); **what the model sent** (a failed call's typed
error and arguments count as evidence too, so "it answered 404" grounds the
status without laundering the model's own arithmetic through its
arguments); and **the tool-rich plane** (`figures_from: [verify]` says which
tool measured the quantity a `number_pattern` describes, so a coding
mission's "3 passed" grounds only against what the test runner actually
printed). A `claim_table: true` block turns figure-checking into arithmetic
over JSON paths into what a tool returned, rather than search. `must_cite`
sets a minimum where silence would otherwise be acceptable. `reading`,
`planes` and `critic` are three further tiers, each off by default until
`core/eval` scores it against a held-out set.

**The supervisor catches a stuck loop instead of a step budget.** Nothing
in this harness decides how many turns a question is worth — `--mission-
steps` survives only as an operator's optional ceiling, unset by default.
`core/runtime/supervisor.py` (on by default; `Bounds(supervisor=
NO_SUPERVISOR)` to opt out) watches for **repetition** at every step
boundary: the same tool call and result three times, three replies in a row
that were not actionable, four steps with no new call *or* result, an A-B-A-B
oscillation. When one fires, the same model is asked in one plain call what
the pattern means and answers `progressing` (a false alarm — that signal's
threshold rises), `nudge` (a note is injected as the next user turn),
or `stuck` (the model writes its best answer with what it has, and
`mission_finished` carries `reason: "stuck"` — never `budget_exhausted`,
because nothing ran out). At most three reviews a run, and the last one
cannot say `progressing`.

---

## How it survives

Every mission leaves a numbered, fsync'd log behind (`core/durable.py`,
`run_id` on `mission_started`), and `--resume <run-id>` (or `MISSION_RESUME`)
picks a killed one back up — the objective comes off the record, the model's
message list is rebuilt from the recorded `tool_call`/`tool_result` pairs,
and there is no second `mission_started`. `SIGTERM` lets a running mission
wind up and write its own `mission_finished` (`reason: "cancelled"`) rather
than dying mid-write. **Liveness is a lock**, not a clock: `RunStore.hold`
means a live run is never mistaken for an orphan and never gets a second
`mission_finished`, while a run genuinely abandoned — no `mission_finished`,
metadata untouched for 60 seconds — gets one appended on the way into the
next mission, so a follower's stream closes instead of hanging forever.

`--replay <run-id>` (or `MISSION_REPLAY`) runs a **finished** mission again
out of its own recording: the model's replies come out of that run's
`model.jsonl` in order and the tool results out of `tools.jsonl`, so no
server is dialled and no model is asked. The replayed run is a *new* run
directory carrying `replay_of` and any `drift`, and grounding runs fresh
over the recorded answer — which is how a change to the grounding grammar
gets scored on last week's runs. `--resume` and `--replay` are not
interchangeable: one continues an unfinished run against a live model, the
other re-runs a finished one against its own recording.

For a platform that would rather subscribe than spawn, `python -m
core.server` (the `[server]` extra) is a read-only HTTP face on the same
run store: `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/events?since=` (the
records as server-sent events) and `GET /runs/{id}/agui?since=` (the same
records through the AG-UI translator). The records are the records — same
names, same fields, scrubbed once at the emitter — and `since=` replays from
a sequence number and then follows until `mission_finished`. There is no
HTTP door *into* a running mission; steer a run from whatever started it.

---

## How it is measured

```
python -m core.eval check                    # refuse a suite that cannot be graded
python -m core.eval run     --out DIR -- …    # spawn every mission, capture the stream, score it
python -m core.eval measure --out DIR -- …    # the same suite over a matrix of configurations
python -m core.eval score   --runs DIR        # score run directories that already exist — no GPU
```

A behavioural change nobody scored is a change nobody can defend, which is
why `--protocol native` and the three deeper grounding tiers all ship off:
none becomes a default until `core/eval` scores it against a held-out
split. `measure` runs the same suite against one endpoint over a matrix —
`direct` vs `--swarm`, `json` vs `native`, each grounding tier on vs off —
and writes the table those defaults are waiting on, recording every run so
the table reproduces with no GPU. `--replay` plus `score` is how a
grounding change is measured on runs that already happened, rather than the
noise between two fresh samples.

The whole of it — the mission shape, the flags, the held-out split, the KPI
columns, the recording format and how a platform writes its own suite — is
**[`EVAL.md`](EVAL.md)**.

**Usage is reported, never estimated.** Every backend's `usage` — prompt and
completion tokens, whatever extras the provider sent — rides the record its
call produced; `mission_finished` carries the run's totals and `elapsed_s`.
Absent rather than zero when a provider (commonly a local one) said
nothing. Cost is optional and comes only from a `pricing:` block a
deployment writes in `.judais-lobi.yml` — never from a price list in this
repository, because prices move and differ per account.

---

## How it embeds

Six objects and a loop is the whole library API:

```python
from judais_lobi import Bounds, Model, Observer, Personality, Run, Store, ToolPlane, Tools

bus = Tools(root=".").bus                                 # SAFE, sandboxed, audited
run = Run(Personality(system_message="You are Tai."),     # what the model is told
          ToolPlane(bus=bus, offered=["read_file"]),      # the only way out
          Bounds(), Store(), Observer(), Model(ask=my_chat_fn))
print(run.run("what does this repository build?").answer)
```

Each object owns one class of fact: `Personality` what the model is told and
held to, `ToolPlane` the only way out and who may say yes to it, `Bounds`
everything that can stop a run, `Store` what survives the process,
`Observer` every record out, `Model` the client and the protocol.
`my_chat_fn` is `messages -> str`: the loop is confined to one injected
callable and cannot ask a backend anything you did not offer. Almost every
default above means *nothing* — no ceiling, no clock, no durable log — so
you add what you want and pay for nothing else; the one exception is the
**supervisor**, which `Bounds()` carries by default (`Bounds(supervisor=
NO_SUPERVISOR)` opts out).

**The CLI is a client of this**, not a second implementation: `judais
--mission` is argparse and then these same six objects handed to this same
`Run`. `from judais_lobi import contract` is the wire as data —
`contract.conforms(record)` answers "is this one of ours" without a
consumer keeping its own copy of the rules.

**A mission does not need an MCP server.** With no `--mcp-stdio`/`--mcp-url`
the plane is this package's own registered tools, governed by the same
profile and sandbox as everything else; the "needs a server" refusal fires
only when a skill's closed set names a tool this host has not got.

If you are wiring this framework into a platform — a personality,
capabilities as MCP tools and a skill manifest, driving it as a subprocess,
pinning a release — that is **[`PLATFORMS.md`](PLATFORMS.md)**, meant to be
sufficient on its own: everything in it is held against the code by
`tests/test_platforms_doc.py`. **A platform integrates from `PLATFORMS.md`
alone; the conformance kit under `tests/conformance/` goes red the day the
contract breaks** — two files a platform copies into its own repository,
edits one dict in, and runs with no model, no server and no credential.

**[`CONTRACT.md`](CONTRACT.md)** is the seam itself, and **from v1.0.0 it is
frozen for the whole of the 1.x major**: `SCHEMA_VERSION` will not move,
`EVENTS`/`OPTIONAL`/`CLI_FLAGS`/`ENV_VARS` only grow, `FIELDS`/`OUTCOMES`/
`EXIT_CONTRACT` do not change meaning. A breaking change is 2.0.0, announced
as such, and a 1.x pin goes on working. What is *not* frozen: the console
(stdout is prose for a person and was never part of the contract), the
prompts a model is shown, and everything under `core/` that is not
`contract.py`.

```python
from core.runtime import contract
assert contract.SCHEMA_VERSION == 1     # fails at import, which is cheap
problems = contract.conforms(record)    # [] when the record is fine
```

`conforms` is pure and standard-library only, importing nothing this repo
owns, so a consumer that cannot import an agent framework can vendor that
one file and have the whole seam.

---

## The mission stream, in brief

`--events` writes what a mission does as NDJSON — one JSON object per line,
flushed as it happens — because `run()` returning a transcript at the end is
the wrong shape for anything that has to *show* a mission while it runs.

```
--events -        stdout, for a person with jq
--events fd:N      an inherited descriptor — what a harness uses
--events PATH      a file, opened for append
```

**stdout is prose for a person and must not be parsed.** The event sink is
the only machine channel.

Eleven record types (`contract.EVENTS`), in the order a run tends to
produce them: `mission_started`, `step_started`, `reply_rejected`,
`tool_call`, `tool_result`, `gate_requested`, `answer_delta`, `answer`,
`grounding`, `mission_finished`, `model_state`. Two are worth a sentence
each. `answer_delta` streams the answer while the model is still writing
it — `part` restarts at 0 per model call, concatenating `text` over `part`
gives the streamed answer, and it is **provisional**: the `answer` record
that follows is always the authority, having been through the grounding
path that may append a caveat. Zero deltas is normal (`--no-stream`, a
non-streaming backend, a turn that called a tool instead of answering).
`model_state` explains a **wait**, not a call: a healthy request emits
nothing, and this appears only while the model is `cold`, `queued`,
`loading` or `absent`, closing with `loaded` once the wait is over.

Every event's required and optional fields, the five outcome words, the
exit contract and what counts as a breaking change are
**[`CONTRACT.md`](CONTRACT.md)** — the human rendering of
`core/runtime/contract.py`, held to it by a test.

### The mission-mode surface

These flags are a **contract**: `core/runtime/contract.py` publishes them as
`CLI_FLAGS`, a test asserts the parser takes every one, and a program that
spawns this harness may rely on them. The rest of `--help` is a person's
surface and may move. Table in `CLI_FLAGS` order:

| flag | env | what it does |
| --- | --- | --- |
| `--mission` | — | run as a mission rather than a chat turn |
| `--mcp-url` | `MCP_URL` | a tool plane, over streamable HTTP. **Repeatable**, and combinable with `--mcp-stdio` (below) |
| `--mcp-stdio` | `MCP_STDIO` | a tool plane to spawn on this host, as a command line. **Repeatable**. The first server's tools are namespaced `mcp.`, the next `mcp2.`, or write `name=<command>` |
| `--mcp-token` | `MCP_TOKEN` | bearer token for `--mcp-url`, paired with the URL in the **same position**. **Prefer the env var** — an argument is visible in `ps` |
| `--mcp-timeout` | `MCP_TIMEOUT_S` | per-call timeout for MCP tool calls, in seconds — a property of the platform holding the other end, like `--gate-wait`. Default 30; non-positive means the default |
| `--mission-steps` | — | an operator's optional ceiling on **model turns**, parse-error turns included. Unset means no ceiling (`--mission-steps 0` too). Under `--resume` it is read as further steps; unset, a resumed run keeps whatever ceiling it started with |
| `--mission-seconds` | `MISSION_SECONDS` | wall-clock cap on the whole run. Unset is unbounded; checked between steps and before each model call |
| `--provider` | — | `openai`, `mistral`, `anthropic` or `local`. `anthropic` needs `pip install 'judais-lobi[anthropic]'` and `ANTHROPIC_API_KEY` |
| `--model` | — | which model on that provider |
| `--profile` | `JUDAIS_LOBI_PROFILE` | `safe` (default), `dev`, `research`, `ops`, `god` — see [How it is governed](#how-it-is-governed) |
| `--unsandboxed` | `JUDAIS_LOBI_SANDBOX=none` | run tool subprocesses with no isolation |
| `--skill` | `MISSION_SKILL` | a `SKILL.md` manifest, a directory holding one, or a first-party pack's name |
| `--swarm` | `MISSION_SWARM` | stage the mission when it needs staging — see [`--swarm`](#--swarm--staged-decomposition-when-it-is-needed) |
| `--events` | `MISSION_EVENTS` | where the NDJSON account goes out: `-`, `fd:N`, or a path |
| `--history` | `MISSION_HISTORY` | a JSON file of prior conversation turns, seeded as real role-tagged chat turns ahead of the objective |
| `--gate-tool` | — | a tool to offer and refuse to call, repeatable — see [How it is governed](#how-it-is-governed) |
| `--approval` | `MISSION_APPROVAL` | an approval id somebody already decided, lifting that one tool for this run |
| `--resume` | `MISSION_RESUME` | carry on a recorded mission by its run id — see [How it survives](#how-it-survives) |
| `--temperature` | — | sampling. Unset sends **nothing**; the server's own default applies |
| `--top-p` | — | nucleus sampling. Unset sends nothing |
| `--seed` | — | a seed where the server honours one — not a determinism guarantee |
| `--protocol` | `MISSION_PROTOCOL` | `json` (default) or `native` — tools declared as functions, `tool_choice=required`, several calls per turn. Off by default until measured |
| `--no-stream` | `MISSION_STREAM=off` | ask for the whole reply at once instead of `answer_delta` fragments |
| `--control` | `MISSION_CONTROL` | where NDJSON commands come **in**: `fd:N`, a FIFO, a path, or `-` — see [Talking to a mission while it runs](#talking-to-a-mission-while-it-runs----control) |
| `--gate-wait` | `MISSION_GATE_WAIT` | seconds a run waits at a gate for a `gate_decision` on `--control` before ending the turn at `awaiting_approval`. `0` = never wait; default 300 |
| `--replay` | `MISSION_REPLAY` | run a recorded mission again from its own recording — see [How it survives](#how-it-survives) |
| `--grant` | — | pre-authorise capability scopes for this run — see [How it is governed](#how-it-is-governed) |
| `--campaign` | — | run a campaign: a plan of missions — see [Campaigns](#campaigns--a-plan-of-missions) |
| `--campaign-plan` | — | the same, from a `CampaignPlan` JSON or YAML file |

### The published environment

| variable | what it does |
| --- | --- |
| `MCP_URL` / `MCP_STDIO` / `MCP_TOKEN` | environment forms of the three MCP flags above |
| `MCP_CLIENT_NAME` | what this client calls itself in the MCP `initialize` handshake — set it to the agent's name, or a server that governs by principal records every call as anonymous |
| `ELF_PERSONALITY`, `TAI_PERSONALITY` | persona files, on every entry point (`TAI_PERSONALITY` wins where both are set) |
| `LOCAL_API_BASE`, `LOCAL_MODEL` | aim the `--provider local` backend |
| `MISSION_SKILL`, `MISSION_SWARM`, `MISSION_EVENTS`, `MISSION_HISTORY`, `MISSION_SECONDS` | environment forms of `--skill`, `--swarm`, `--events`, `--history`, `--mission-seconds` |
| `MISSION_APPROVAL`, `MISSION_RESUME`, `MISSION_REPLAY` | environment forms of `--approval`, `--resume`, `--replay` |
| `MISSION_PROTOCOL`, `MISSION_STREAM`, `MISSION_CONTROL`, `MISSION_GATE_WAIT` | environment forms of `--protocol`, `--no-stream` (reversed: `off`/`0`/`false`/`no`/`none` turns streaming off), `--control`, `--gate-wait` |
| `JUDAIS_LOBI_PROFILE`, `JUDAIS_LOBI_SANDBOX` | environment forms of `--profile`, `--unsandboxed` |
| `JUDAIS_LOBI_AUDIT` | moves the audit file (a path) or silences it (`none`/`off`); `mission_started.audit_ref` says which |
| `JUDAIS_LOBI_RUNS` | moves the durable run directories, or turns them off; `mission_started.run_id` is present exactly when there is one |
| `JUDAIS_LOBI_APPROVALS` | moves the durable approval records, or turns them off — off means a gate stops a mission and leaves nothing anybody can decide against |
| `JUDAIS_LOBI_MEMORY`, `JUDAIS_LOBI_MEMORY_PRINCIPAL` | turn the memory bank on and partition it — see [Memory](#memory) |

Four more belong to the web tools rather than the mission seam, so they are
not in `contract.ENV_VARS` and nothing on the wire reports them — read at
call time, every one optional: `RESEARCH_ALLOWED_HOSTS` (comma-separated
allow-list; unset means no restriction; a leading dot covers subdomains),
`RESEARCH_MAX_PAGE_BYTES` (default 4 MiB), `RESEARCH_TIMEOUT_S` (default
20), and `SEARCH_PROVIDER` (`duckduckgo` the keyless default, `searxng` with
`SEARXNG_URL`, or one a platform registers with
`core.tools.web_search.register_provider`). `MCP_RELIST_TIMEOUT_S` (default
5) bounds the `tools/list` a mission asks for at every step boundary, so the
catalogue shown to the model is the plane at that boundary.

---

## Memory

Three tiers, three different insertion rules, because pulling too much into
context is as wrong as ignoring retrieval entirely.

**Core memory** — a handful of pinned blocks per principal and skill
(`preference`, `fact`, `lesson`, `persona`), hard-capped around 1,000 tokens,
rendered into the system turn after the tool catalogue of every run. A write
that would breach the cap is refused naming the cap; nothing is evicted to
make room. Changes only through the `memory_write` tool or an operator.

**Recall memory** — one tool, `memory_recall`, over the durable run store
(episodic, by `run_id`) and distilled notes a bounded reflection step writes
at the end of a run that answered (semantic, at most three per run). Ranked
`relevance × recency × importance` — a product, so an old irrelevant note
scores zero — capped at 5 results and ~600 tokens. A titles-only hint (at
most 3, ~150 tokens) may ride the objective turn when something scores; the
model decides whether to spend a call retrieving the rest. A recalled fact
is dated, and re-verifying it is the model's job.

**Working memory** — the per-mission result store, context-window
compaction, the swarm's step summaries: already built, named here so nobody
builds it twice.

Both tools go through the same `ToolBus` as every other tool — gated,
audited, redacted — so a recalled note the model quotes is evidence the
grounding validator can cite. `memory_recall` needs `memory.read` (`safe`
grants it); `memory_write` needs `memory.write` (`dev` grants it), because
pinning a sentence into every future system turn is a durable effect.

Turn it on with an environment variable — there is no flag and no default
directory:

```bash
export JUDAIS_LOBI_MEMORY=~/.judais-lobi/memory     # unset/none/off = no memory
export JUDAIS_LOBI_MEMORY_PRINCIPAL=alice           # default: "default"; attributed, not authenticated
```

The operator's half:

```bash
python -m core.memory stats
python -m core.memory blocks
python -m core.memory add --label house-style --kind preference \
    --body "Answers are short; no preamble." --reason "asked twice" --source operator
python -m core.memory recall "cold start"
python -m core.memory purge --notes
```

A library caller passes a bank directly: `Personality(system_message=...,
memory=MemoryBank(path, principal="alice"))`. See `core/memory/bank.py`.
Direct chat (`--recall`/`--rag`) still runs on the older `UnifiedMemory`
(`core/memory/memory.py` — SQLite plus a FAISS or numpy index); the mission
path uses only the bank.

---

## Campaigns — a plan of missions

`--swarm` is one mission a model decided to break up. A **campaign** is
several missions a *person* decided to run, in an order they wrote down,
with files handed from one to the next:

```bash
lobi --campaign "measure last quarter and write it up" --skill analyst
lobi --campaign-plan ./migration.json --skill analyst
```

A `CampaignPlan` is a DAG of steps, each naming a **task template**
(`templates/*.yaml` out of a mission pack), the capability scopes it needs,
and the artifacts it takes and exports. `--campaign` asks the model to draft
a plan from the message; `--campaign-plan` runs one off disk. Either way the
plan is **approved before any of it runs**: an unapproved plan ends the run
at `awaiting_approval` holding the whole plan on a `gate_requested` record —
the same store, the same `--approve <id>` / `--approval <id>` round trip a
gated tool call uses. `--auto-approve` declines to ask.

Each step is a **child run** (`Run.child`) — its own branch, its own result
store, its own persona — sharing the parent's plane, clock, supervisor,
ledger and durable log. Each is narrowed to `step scopes ∩ template scopes`
before it starts, so a step that never asked for `fs.write` cannot write
even though the run's profile allows it — `--grant` widens the run, a
campaign narrows each step. A step's declared inputs are copied into its
`handoff_in/` and its exports collected from `handoff_out/` after; a step
that promised a file and did not write it **failed**, whatever it said about
itself. A failed step ends the dispatch — a campaign's plan is what somebody
said yes to, and there is no redraw. `--resume <run-id>` continues at the
step after the last one that finished, as a campaign, with its artifacts and
scopes intact.

On the wire it is a staged turn plus one field: every record carries
`branch` (the step's id), the plan rides the first `step_started` as `plan`,
and each step's own `step_started` carries `artifacts: {"in": [...], "out":
[...]}`. Nothing required was added and `SCHEMA_VERSION` did not move.
`core/runtime/campaign.py` is a **subclass of `SwarmRunner`** — a parent
over children, waves, a per-step gate, a checkpoint and a synthesis is one
loop, not a second implementation of the run store, the approvals, the
supervisor or resume.

---

## `--swarm` — staged decomposition, when it is needed

A small local model drowns in one long transcript: by step six the
catalogue lookups that told it what its numbers mean have been pushed out of
attention by governed views, and the answer is written from the part it can
still see. `--swarm` (or `MISSION_SWARM`) puts five small roles over **the
same backend and the same tool bus** — triage, plan, execute, gate,
synthesize. Triage is one cheap call biased toward the ordinary loop, so
every failure of the router falls back to running direct.

Steps that need nothing from each other can run at the same time
(`SwarmRunner(..., parallel=N)`; default `1`, serial); each record then
carries the OPTIONAL `branch` field naming the plan step that emitted it, and
records the turn itself emitted carry none — a consumer that has never heard
of `branch` reads exactly the single ordered stream it always read. Every
stage is bounded by the same `MissionWindow` the direct path uses, resolved
from the backend's real context size — nothing is bounded by a character
count standing in for it, and the synthesizer is given the whole of every
settled step's tool output. A failed gate is put to the supervisor rather
than retried a fixed number of times; there is no `step_budget`, because a
step takes the turns its work takes.

---

## Serving the built-in tools over MCP

`python -m core.tools.serve` publishes this package's *own* tools — `fs`,
`git`, `repo_map`, `patch`, `verify`, `run_shell_command`,
`run_python_code`, the research tools — as MCP tools:

```bash
python -m core.tools.serve                               # stdio, profile safe
python -m core.tools.serve --profile dev                  # code plane on
python -m core.tools.serve --http 127.0.0.1:8765 --token "$MCP_SERVE_TOKEN"
python -m core.tools.serve --list                          # what would be served
```

**One owner, two transports.** There are no tool definitions in the server:
it publishes the descriptors already on the bus and dispatches every call
back through `ToolBus.dispatch`, so the profile check, the sandbox and the
audit log all apply **on the serving side** exactly as they do locally. A
result carries the tool's text plus `structuredContent` holding the whole
`ToolResult`, which `tests/test_mcp_serve.py` asserts is identical to an
in-process call.

`--mcp-stdio` and `--mcp-url` are **repeatable** and may be mixed — how a
platform composes its own governed plane with this one. Each server gets a
namespace (`mcp`, then `mcp2`, `mcp3`, …, or name one on the flag:
`--mcp-stdio 'ours=python -m core.tools.serve'`); a skill's closed set still
names tools the way the server advertises them, and a short name matching
two planes is a refusal telling the author to write the namespace.

---

## Talking to a mission while it runs — `--control`

`--events` is what a mission *says*; `--control` is what it can be *told*.
Before it existed the only lever on a running turn was `SIGTERM` — ending
it. One JSON object per line, on `fd:N` (what a platform uses — no path on
disk to race), a FIFO, a path, or `-` for a person typing at a run. The
vocabulary is closed to four words:

* **`{"control": "inject", "text": "…"}`** — a user instruction, appended as
  a `user` turn immediately before the next model call; that step's
  `step_started` carries it back as `injected: ["…"]`.
* **`{"control": "cancel"}`** — the mission winds up at its next check,
  keeps its transcript, and writes its own `mission_finished` (`incomplete`,
  `reason: "cancelled"`). The process exits normally.
* **`{"control": "cancel_step"}`** — abandon the rest of the current step
  only. A tool already running is left alone; an ask that arrives too late
  is a no-op and says so to the model.
* **`{"control": "gate_decision", "approval_id": "ap_…", "approve": true,
  "decided_by": "dana"}`** — answer a gate while the run is still standing
  at it, bounded by `min(seconds left, --gate-wait)`. A yes is dispatched in
  the same step; a no is recorded and the model told.

Nothing times out into a yes: a wait running out ends the mission at
`awaiting_approval` exactly as it always would. A malformed line, an unknown
word, or a decision signed by nobody is dropped with one sentence on stderr
and the run carries on. There is no HTTP door into a running mission — see
[How it survives](#how-it-survives).

---

## Where to look

If you are **running this from another program**, read:

* [`CONTRACT.md`](CONTRACT.md) — the mission stream, its events, the exit contract
* [`PLATFORMS.md`](PLATFORMS.md) — deploying judais-lobi as a platform's agent
* [`EVAL.md`](EVAL.md) — the eval harness, and how a platform writes its own suite

If you want to understand the **current implementation**, inspect:

* `judais_lobi.py` — the library façade; `from judais_lobi import Run` and everything it is built from
* `core/runtime/contract.py` — the seam a consumer pins, as data
* `core/runtime/run.py` — the loop, as six objects: `Run(personality, plane, bounds, store, observer, model)`; `Run.arun` is the loop, `Run.run` the synchronous façade
* `core/runtime/mission.py`, `mission_stream.py`, `swarm.py`, `campaign.py` — the `MissionRunner`/`SwarmRunner` adapters that build those six, the NDJSON account, staged decomposition and campaigns
* `core/runtime/skills.py` — the `SKILL.md` loader: closed tool set, prompt, grounding grammar
* `core/skills/library/` — the three first-party packs, loaded by `core.skills.load`/`packs`
* `core/runtime/grounding.py`, `results.py`, `reading.py` — the claim validator, the per-mission result store, the field-misreading tier
* `core/runtime/replay.py` — recorded model/tool calls and `--replay`
* `core/eval/` — the eval harness: suite, run, score, measure
* `core/critic/mission.py` — the mission-tier critic (`advisory: true`, local first)
* `core/runtime/schema_check.py` — argument validation against a tool's own JSON Schema
* `core/runtime/answer_stream.py` — `answer_delta` fragments out of a half-written reply
* `core/runtime/control.py` — the `--control` command vocabulary
* `core/runtime/approvals.py`, `resume.py` — the durable approval record; the resume door, replay and orphan reconciler
* `core/runtime/usage.py`, `budgets.py` — the usage ledger; steps, seconds and cancellation
* `core/runtime/context_window.py`, `messages.py` — keeping a conversation inside the model's window
* `core/runtime/backends/`, `provider_config.py`, `core/unified_client.py` — `openai`, `mistral`, `local`, `anthropic`, and what each declares it can do
* `core/runtime/agui.py` — the AG-UI translator
* `core/durable.py` — atomic writes and `RunStore`
* `core/bounding.py` — the tool-result cap and cut
* `core/redact.py` — the one redactor
* `core/memory/bank.py` — the memory bank; `core/memory/memory.py` — long-term chat memory (FAISS or numpy)
* `core/tools/` — `ToolBus`, capability engine, sandbox (`sandbox.py`), the mission root (`root.py`), the MCP bridge and server (`mcp_client.py`, `serve.py`), consolidated tools (`fs`, `git`, `verify`, `repo_map`, `patch`)
* `core/policy/` — `profiles.py` (the five profiles), `audit.py` (the append-only log)
* `core/context/`, `core/patch/` — repo map extraction and the exact-match patch engine the `coding` pack uses
* `core/judge/`, `core/critic/`, `core/campaign/` — composite judge and candidate sampling; the coding-tier external critic; a campaign plan's own facts (schema, legality, scope intersection)
* `core/kernel/` — the earlier phases' state machine and workflow templates
* `core/cli.py` — the CLI: argparse, then the same six builders `judais_lobi.py`'s docstring names
* `core/server/` — the `[server]` SSE extra
* `lobi/`, `judais/` — the two shipped personalities
* `main.py`, `setup.py` — the entry point and the package

---

## Roadmap and status

**[`ROADMAP.md`](ROADMAP.md)** is the only roadmap: §1 is where the project
stands, §2 the plan phase by phase, §3 the principles, §4 how you know it is
no longer a toy, §5 the history kept because docstrings and this file quote
it. At v1.0.0 every phase through 15 has shipped; what remains is the
mission-pack `templates/` roles composed as their own `Run`s, and the
measurements `core.eval measure` is for — swarm versus direct, `json` versus
`native`, each grounding tier on versus off — run against a real endpoint,
which is what gates every one of those defaults moving.

The February documents are kept as history: [`MANIFESTO.md`](MANIFESTO.md)
is why this exists (an agent, not a chatbot — local, governed, honest), and
`project.md` is the plan as first drawn. ROADMAP §5 quotes both.

### Release history

One line each. The commit for every one of these is `release: <version> — …`.

| version | date | what it was |
| --- | --- | --- |
| 1.0.0 | 18 Aug 2026 | **the freeze**: `SCHEMA_VERSION` 1 frozen for the 1.x major (`CONTRACT.md` §1.0). The framework's conduct text rendered once; `mission_result` pages text results; figures ground where they were measured (`figures_from:`); a mission has a root (`core/tools/root.py`); the sandbox runner is carried per call; liveness is a lock (`RunStore.hold`), not a clock; the supervisor treats a new call OR a new result as progress and refunds a `progressing` verdict on `no_new_evidence`; `--mission-steps 0` is no ceiling; an unreachable server exits non-zero |
| 0.17.0 | 18 Aug 2026 | the `coding` pack (multi-file, verified by running the repository's tests); **campaigns on `Run`** (`--campaign`/`--campaign-plan`, approval as a durable record, artifact handoff); **`--grant`** (session-scoped scopes); the native round trip keeps opaque provider fields; the catalogue is re-listed at every step boundary; grounding — the echo rule, the clock mask, failed results as typed evidence |
| 0.16.0 | 18 Aug 2026 | **one runtime** (Phase 11): `core/runtime/run.py` — `Run(personality, plane, bounds, store, observer, model)`; `MissionRunner`/`SwarmRunner` become adapters; the library API `from judais_lobi import Run …` and the CLI as its client; `--mission` on the built-in tools with no server; `[server]` SSE extra; `model_state` (the eleventh event); three first-party skills — `research` (+ the `research` profile), `analyst`, `coding`; mission packs by name; memory (core/recall/working); the built-in tools served over MCP and multi-server bridging |
| 0.15.0 | 17 Aug 2026 | the step budget is gone: `--mission-steps` unset means no ceiling, and `core/runtime/supervisor.py` watches for repetition instead — three reviews a run, the last cannot say `progressing` |
| 0.14.1 | 17 Aug 2026 | the swarm stops starving itself: one `MissionWindow` bounds every role and every sub-mission at the model's real size, the synthesizer sees every settled step's whole tool output |
| 0.14.0 | 17 Aug 2026 | `--provider anthropic` (default `claude-opus-5`); the offered set follows a bus that grows mid-run; the swarm gets the critic and staged `--resume`; `ApprovalStore.reconcile` called on the way in |
| 0.13.0 | 17 Aug 2026 | Phase 10: the eval harness (`core/eval/`, `EVAL.md`), recording + `--replay`, the reading/planes/critic grounding tiers off by default |
| 0.12.2 | 17 Aug 2026 | the credential redactor is linear on long unbroken payloads (a 200 KB tool result took minutes; now ~50 ms) |
| 0.12.1 | 16 Aug 2026 | `--gate-wait` / `MISSION_GATE_WAIT`: an unattended caller can turn the in-turn gate wait down to `0` |
| 0.12.0 | 16 Aug 2026 | `answer_delta` at the source, a `--control` channel into a running mission, an AG-UI translator |
| 0.11.0 | 16 Aug 2026 | native tool calling behind `--protocol native`; arguments schema-checked before dispatch; a byte-stable prompt prefix, and a window that evicts tool round trips first |
| 0.10.0 | 16 Aug 2026 | durable and bounded: the fsync'd run log and `--resume`, a wall clock and a cancel that finish cleanly, the usage ledger and `elapsed_s`, approvals as durable records |
| 0.9.0 | 15 Aug 2026 | safe by default: sandbox on, the `safe` profile, audit on every bus, one redactor |
| 0.8.2 | 15 Aug 2026 | the honest stream: it opens before triage, the conversation is windowed, one owner for the result cut, Mistral over httpx, a bwrap that runs |
| 0.8.1 | 15 Aug 2026 | the wheel stops shipping `tests/` |
| 0.8.0 | 15 Aug 2026 | the separation from the reference deployment this framework was first proven in: the contract as data, the `tai` entry point, the `mission` extra, `PLATFORMS.md` |

### Status

**v1.0.0 — 5,890 tests collected** (`pytest --collect-only -q`). Mission
mode, skill manifests, the grounding validator, `--swarm`, campaigns, the
NDJSON mission stream and the published contract are all in this release.

---

## License

GPLv3 — see [LICENSE](LICENSE).
