# Deploying judais-lobi as a platform's agent

This is the guide for the other side of the seam: you have a platform, you want
it to have an agent, and you would rather not write one. It is also the record
of what was learned deploying this framework once, so that the second platform
does not rediscover it.

**TAIPAN is the worked example throughout.** It is a governed
narrative-influence platform; its mission agent is called Tai; Tai is this
framework, spawned as a subprocess, pointed at TAIPAN's own tools and told
TAIPAN's own rules. Everything below is stated generically and then shown as
TAIPAN does it, because one deployment is not a design and every sentence that
only makes sense for TAIPAN is a sentence that belongs in TAIPAN.

---

## The shape

judais-lobi is a **CLI and a library**, and a platform integrates it as four
separate decisions:

1. **A personality.** Who the agent is, what it may claim, what register it
   writes in. A TOML file the platform owns. `core/contracts/schemas.py`.
2. **Capabilities.** Tools over MCP, plus a `SKILL.md` manifest that closes the
   tool set, supplies the operational knowledge, and states the grounding
   grammar. `core/tools/mcp_client.py`, `core/runtime/skills.py`.
3. **A driver.** The platform spawns `judais --mission …`, reads the NDJSON
   mission stream off a descriptor it passed, and renders it.
   `core/runtime/mission_stream.py`, `CONTRACT.md`.
4. **A pin.** A git tag of this repo, deployed by name, bumped deliberately.

None of the four is optional, and each fails differently when it is skipped —
which is the reason they are four things and not one config file. A missing
personality is an agent that will not start (`main_tai` refuses); a missing
manifest is an agent that starts holding the whole bus with no grounding check;
a missing event sink is a pane that shows a spinner; a missing pin is a host
whose harness version can only be established by reading its code.

The framework supplies mechanisms. **The platform supplies content**, and it
keeps that content in its own repository, where its own tests can hold the
prompt against the code that enforces it. That is not tidiness: a personality
asserting a rule the platform does not enforce is worse than no personality,
because it tells an analyst the agent is bound by something it is not.

---

## Personalities

### The file

A personality is a `PersonalityConfig` written down. `PersonalityConfig.from_file`
is a **loader and not a second schema**: the keys are exactly that model's
fields, and an unknown key is refused by name at load time rather than absorbed.
A typo'd `system_prompt` that silently produced an empty system message would be
discovered by reading the agent's output, which is the worst possible place to
discover it.

Suffixes: `.toml`, `.json`, `.yaml`, `.yml` — closed, and an unknown suffix is
refused rather than parsed hopefully. YAML needs `pyyaml`; TOML on Python 3.10
needs `tomli` (3.11+ has `tomllib` in the standard library).

| field | required | default | what it is |
| --- | --- | --- | --- |
| `name` | **yes** | — | what the agent is called in its banner, its answer header, and every refusal |
| `system_message` | **yes** | — | the prompt. Everything the agent *is* |
| `examples` | no | `[]` | few-shot `(user, assistant)` pairs. Optional in a file although the field is required on the model: the pairs exist to pin a *voice*, and a governed register has no voice to pin. Omit them and you get **none** — never a set borrowed from another personality |
| `text_color` | no | `cyan` | the console style |
| `env_path` | no | `~/.elf_env` | execution-environment directory; API keys load from its `.elf_env` file. A direct dotenv-file path remains supported |
| `rag_enhancement_style` | no | `""` | how retrieved material is to be used in an answer |
| `default_provider` | no | `None` | the backend when no `--provider` is passed |
| `default_model` | no | `None` | the model when no `--model` is passed |

`--personality` swaps the config and nothing else: the same `Agent` class, the
same memory, the same tools (`core/cli.py`, `_build_agent`). JudAIs and Lobi stay
compiled-in Python and are untouched by any of this.

### How a platform points at one

Three ways, and they are consulted in this order by `core.cli.tai_personality_path`:

1. **`$TAI_PERSONALITY`** — a path. Must exist, or it is not consulted further.
2. **`$ELF_PERSONALITY`** — the same, under the older name. Both aliases are
   live; `--personality` itself defaults to `$ELF_PERSONALITY` for every agent,
   so this is the one variable that works for `lobi`, `judais` and `tai` alike.
3. **An installed package resource** — `taipan.agent.personalities/tai.toml`,
   via `importlib.resources`. A guarded import: a deployment package that is
   simply not present here is an ordinary `None` and not an error, because this
   framework is installable and runnable on its own.

An explicit `--personality` on the command line beats all three (`main_tai`
checks `sys.argv` before it searches).

**There is no fourth step, and no guess.** `tai_personality_path` used to search
three fixed directories under `$HOME` and a sibling of the cwd, with another
repository's source layout frozen into a constant — one developer's laptop,
installed onto every other machine. A guess that lands on the *wrong* checkout is
worse than no guess: it starts an agent whose stated governance rules are not the
rules it loaded, and the banner says the right name either way. So the third
outcome is a **refusal** naming exactly what was consulted, which variable was
unset and which pointed at nothing (they are different repairs), and how to point
either at a file. Exit status 2.

TAIPAN takes route 2: `MissionAgent.environ()` exports
`ELF_PERSONALITY=<…>/taipan/agent/personalities/tai.toml` into the subprocess.
Route 3 exists for a platform installed *beside* the framework in one
environment, where the file that matches the running code is the one shipped with
it.

### Adding a new named agent

A personality reachable only by asking for a *different* agent does not have a
name. Tai shipped for weeks as a TOML file plus `--personality`, which made it
loadable — but the only way to run it was
`python main.py lobi --personality …/tai.toml`, so the mission agent had to
impersonate Lobi to start, its banner said Lobi, and nobody reading `main.py`
would learn Tai existed.

Three edits give a personality a name:

1. **An entry function in `core/cli.py`.** `main_tai` is the pattern: no
   arguments, reads `sys.argv` itself, resolves the personality file, appends
   `--personality <path>` if the caller did not pass one, and calls `_main`. For
   a personality your platform *ships*, it is shorter — resolve the resource and
   hand it over.
2. **A row in `main.py`'s `AGENTS` table**, `{"name": (main_fn, "one line for
   --help")}`. The dispatcher's `--help` is generated from that table, so a name
   absent from it is a name nobody discovers.
3. **A console entry point in `setup.py`**, in the shape of the two that were
   already there:

   ```python
   entry_points={"console_scripts": [
       "lobi = core.cli:main_lobi",
       "judais = core.cli:main_judais",
       "tai = core.cli:main_tai",
   ]},
   ```

   After `pip install -e .`, `tai "…"` is a command.

Note that a platform does **not** have to do this. TAIPAN spawns `judais` and
exports `ELF_PERSONALITY`; the `tai` entry point exists so that a person on the
pool can start the same agent by typing its name.

### What does not belong in a personality

A personality states **what is true of this deployment and this agent's
standing**. It must not state **what happened on this turn**, and it must not
state anything the platform does not actually enforce.

* **Deployment facts belong here.** "The model that drives a mission is local" is
  a property of TAIPAN's arrangement, it costs money and latency to give up, and
  a prompt is the right place to say it. Same for the three rules Tai is bound by
  — each one is enforced somewhere in TAIPAN's repository, and there is a test in
  *that* repository holding the prompt's text against the enforcement.
* **Turn facts belong in a grounding check.** "I used the SDK" is a claim about
  which plane was called *this turn*, and a prompt cannot check it. Asked to "use
  the SDK" on a pane that grants no code plane, Tai wrote "Using the TAIPAN SDK I
  accessed…" while calling only MCP tools — contradicting the sidebar on the same
  page. The prompt fix was to make the claim conditional; the real fix is a check
  keyed on the tool set actually offered, and that lives with the validator here.
* **Absolute claims rot.** A line asserting that no mission prompt ever reached a
  service off the machine was true when written and stopped being true when web
  search was added. The repair was to delete it rather than soften it, because
  the absolute form keeps being read long after it stops holding — and not even
  to restate it as a quotation, because a test that greps the file by substring
  cannot tell a historical quotation from a reinstated rule.
* **Anything the framework already knows.** Tool names, the catalogue, the shape
  of a result. Those come from `tools/list` and the manifest, once, and a second
  copy in the prompt disagrees with the first the day a server changes a
  description.

---

## Capabilities

### Tools, over MCP

Everything the agent can reach in a mission arrives through `tools/list` and is
dispatched through the agent's own `ToolBus`. No store, path or compute plane is
touched from the mission path; if a platform wants the agent to be able to do
something, it publishes a tool.

```bash
judais --mission --mcp-url https://host/mcp "…"      # env: MCP_URL
judais --mission --mcp-stdio 'python -m my_server' "…"   # env: MCP_STDIO
```

Passing both is a refusal naming both. Passing neither is a refusal, because
there is nothing to discover otherwise.

Three environment variables carry the rest:

* **`MCP_TOKEN`** — the bearer token for `--mcp-url`. There is a `--mcp-token`
  flag and you should not use it: an argument is visible in `/proc/<pid>/cmdline`
  to every process on the host, and the whole safety argument for a shared pane
  is that authority rides on the analyst's own credential.
* **`MCP_CLIENT_NAME`** — **what this client calls itself in the `initialize`
  handshake**, and the single most easily missed line in an integration. It
  defaults to `judais-lobi`. Set it to the agent's name.

  A server that governs by principal still has to be able to say *which agent
  acted*, and it can only know what we tell it. The handshake went out with no
  `clientInfo` at all, so the SDK's own default travelled, and TAIPAN — which
  builds its audit actor as `<person> via agent:<clientInfo.name>` — recorded
  every one of Tai's calls as `analyst via agent:mcp`. That is not cosmetic:
  TAIPAN's bake-off harness scores an agent by filtering the shared audit trail
  on the actor, and therefore measured Tai as having called **no tools at all**
  across a whole suite it had in fact worked through correctly. An agent that
  cannot be told apart in the audit cannot be graded, credited, or held to
  anything.
* **`LOCAL_API_BASE` / `LOCAL_MODEL`** — see *Driving it*.

Each discovered tool is registered as a `ToolDescriptor` whose executor
dispatches `tools/call`, namespaced **`mcp.<name>`** so a server discovered at
runtime cannot shadow `fs`, `git` or `run_shell_command` by choosing their names.
Capability gating, the sandbox and the audit log apply to it exactly as to a
compiled-in tool. Its `SandboxProfile` follows the transport: a tool reached over
HTTP is registered with `allow_network=True`, a stdio server's tools are not, so
a sandbox that denies the network by default cannot cut a bridged tool off from
the server it *is*. A platform registering its own `ToolDescriptor` owes the same
declaration — a tool that reaches the network says so in its profile, or the
sandbox will take it away without saying anything. The tool's JSON Schema is carried whole on the descriptor, so
the catalogue the model reads says `type (string: dataset|model|service)` and not
just `type` — types, `required` and enums are what decide whether a *first* call
to a faceted search works.

### The skill manifest

`--skill DIR` (or `--skill DIR/SKILL.md`, or `MISSION_SKILL`) loads one manifest:
YAML frontmatter between `---` fences, then a Markdown body. It needs `pyyaml`,
which is why `[mission]` and not `[mcp]` is the extra to install. Point it at a
directory holding several skills and it refuses, listing them by name.

Four things come out of a manifest and nothing else does — and one thing it is
refused for, `sandbox`, below.

**`allowed_tools` — the closed set.** A list of tool names, intersected with what
the bridge actually discovered, **in manifest order**, because the order a skill
author chose is the order the catalogue is read in.

* A bare name matches a namespaced one: write `catalog_search_assets`, get
  `mcp.catalog_search_assets`. Matching reduces on separators rather than on a
  list of known prefixes (`core/tools/descriptors.py`, `same_tool`), so a
  manifest written in any convention resolves — including one nobody has invented
  yet. An entry that matches *two* discovered tools is a refusal asking you to
  name the namespace, rather than a coin flip.
* Suffix an entry with **`?`** to mean *use it if the server offers it*. The same
  marker the `inputs:` grammar already uses for an optional input, so an author
  does not learn a second convention. Everything without it is required.
* **A manifest naming a missing required tool refuses loudly**, listing every
  missing name *and* everything that was on offer. It is never a silent
  narrowing, and never a run: a mission missing the tool that answers its
  question will answer it from the model's memory instead, and the transcript
  will look completely ordinary. A closed set where every entry is optional and
  none was discovered is refused for the same reason.
* A closed set that names a **code-plane tool that runs on this host** — a
  shell, an interpreter, a `pip install`, by its bare descriptor name — is
  refused unless the manifest also declares `sandbox: bwrap`. See `sandbox`
  below.

**Prompt text.** The operational frontmatter fields and the whole Markdown body,
appended to the personality's system message — who you are, then what you are
doing. Six fields are rendered first, in this order and with these labels:
`when_to_use`, `inputs`, `retrieval_strategy`, `ranking`, `policy`,
`evidence_requirements`. `output_format` is rendered **last**, after the body,
because it is the instruction a model is acting on when it stops.

**Fields this loader has never heard of are rendered into the prompt anyway**, as
`Label:\nvalue`, with underscores turned to spaces. A skill is content, and a
harness deciding that an unrecognised field is noise would be the framework
overruling the platform on its own operational knowledge. Only the structural
keys are held back — `name`, `skill_id`, `version`, `description`,
`allowed_tools`, `grounding`, `sdk_import` — because each already reaches the
model another way.

**`grounding` — the identifier grammar, and the tiers a platform switches on.**
A mapping, interpreted by `core/runtime/grounding.py` and never by the loader.
Absent means no validator is built and the transcript's grounding report stays
`None` rather than claiming a clean check: a check that could not run reports
*no opinion* and never a pass, because a fabricated "grounded" is a governance
claim. The keys are `identifier_pattern`, `number_pattern`, `ignore`,
`max_repairs`, `must_cite`, `claim_table`, `reading`, `critic` and `planes`;
anything else is refused by name, listing the ones that exist. The README covers
`identifier_pattern`, `ignore`, `max_repairs`, `must_cite` and `claim_table`.
`reading`, `critic` and `planes` are **off by default** and are the ones a
platform has to decide about:

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

* **`planes:` is how a platform declares its tool families — the framework never
  learns their names.** A plane is a set of tools and the phrases an answer uses
  when it claims them, and the check fails an answer that claims one nothing on
  it was dispatched from **this run**. "I used the SDK to recompute the figure"
  carries no identifier, no figure and no claim-table entry, so every mechanical
  tier reports *nothing considered* and the sentence goes out grounded while
  describing work that did not happen — and it is the single most expensive
  sentence in a governance report to get wrong, because a reader who believes
  the SDK ran believes the number was computed rather than remembered. Which
  tools constitute "the SDK", and what your agents say when they claim it, are
  facts only the platform has; a framework that hard-coded either would be
  naming somebody else's tool families for them. Names match by the same
  `same_tool` rule `allowed_tools` uses, so a bare name matches the bridged
  `mcp.` spelling. A plane with no `tools`, or no `claims`, is refused: a
  half-declared plane silently checks nothing.
* **`critic: true` does not need a frontier key.** The provider is resolved
  **local first** — with `LOCAL_API_BASE` set, the critic is the same weights
  the mission already leased, given an adversarial prompt — so a deployment
  running entirely on its own hardware still gets a second opinion. A hosted
  provider is reached **only** where the deployment wrote `critic: {enabled:
  true}` into `.judais-lobi.yml` or `~/.judais-lobi/critic.yml` *and* a key
  resolves for one of the providers that config names (unnamed, it defaults to
  openai/anthropic/google, each looked up by its `*_API_KEY` variable and then
  the keyring). Posting a governed draft to another company is a handling
  decision a platform makes explicitly rather than one a framework makes by
  noticing an API key in the environment. With neither, the row says `skipped`
  and names what was missing. The verdict is a `critic` row
  in `grounding.checks` marked `advisory: true`, **beside** the record's
  `grounded` and never inside it — see `CONTRACT.md`.
* **`reading: true` needs `claim_table: true`** and is refused without it: the
  tier reads the table for the path each figure came from, asks a reader what
  that field holds *before* showing it the sentence, and then asks whether the
  sentence says the same thing. It is the one tier that spends model calls —
  two per claim, capped at twelve claims — which is why it is off and why it
  runs last, after every mechanical check.

None of the three is on by default anywhere, and a platform should measure
before switching one on for good: `EVAL.md` is the harness, and `--replay` lets
the decision be made on runs the platform already has.

**`sdk_import` — what the platform calls itself to Python.** A single module
name, e.g. `sdk_import: taipan`. A list or a number is refused rather than
coerced, because `sdk_import: [acme]` would render as ``import ['acme']`` in a
sentence handed to a model and the model would write that line.

It exists for the swarm. `--swarm` plans a mission as steps, each tagged with a
**rung** — how the step will be done:

| rung | what it means | offered when |
| --- | --- | --- |
| `tool` | a registered tool | always |
| `code` | code via a code-execution tool | always |
| `code+sdk` | code that also fetches platform data itself, `import <sdk_import>` | **only when `sdk_import` is declared** |

A manifest that declares none does not get a vaguer sentence — **it does not get
the rung**, and the planner's prose lists only the rungs it may use, with the
plan validator refusing the others by the same list. "Import the platform SDK"
with no SDK named is an invitation to invent a module, and a 20B accepts the
invitation. This is also why the name is a manifest field rather than a constant:
the framework drives whatever platform it is pointed at, and it cannot know what
that platform is called.

TAIPAN's five skills each declare `sdk_import: taipan`.

**`sandbox` — the code plane never arrives by accident.** A closed set that names
a tool which runs code *the model composed* must also declare `sandbox: bwrap`, or
the resolve refuses, naming the tool, the missing declaration and the fix:

```yaml
allowed_tools: [governed_read, run_shell_command]
sandbox: bwrap
```

A governed mission that can run arbitrary code on the host without isolation is
the hazard TAIPAN's `HOSTED_SDK_CODE_PLANE_DESIGN.md` names. It is not a hazard a
hosted platform should discover from a transcript, so it is a refusal at the door
— before the model is asked anything, because a mission that has already run has
already run whatever it ran.

* **Which tools those are is derived from scopes, not typed out.** Any descriptor
  asking for `shell.exec`, `python.exec` or `pip.install` (`core/tools/
  descriptors.py`) — today `run_shell_command`, `run_python_code` and
  `install_project`, and whatever is registered next, on the day it is registered.
  A bridged spelling does **not** count. `mcp.run_python_code` is a tool on a
  discovered server — the mission sends `tools/call` and the interpreter runs on
  the far end — so `sandbox: bwrap`, a wrapper this bus puts around a subprocess
  it spawns, would isolate nothing about it. The rule is `tool_key` equality:
  the bare name is this process's own descriptor and is gated; a namespaced one
  is the server's and is not. **A platform that bridges a shell is responsible
  for the isolation on the server side**; what this harness governs it with is
  the closed set, the `mcp.call` capability and `--gate-tool`, and it does not
  claim to have sandboxed it. `verify` is deliberately out:
  it ends in a subprocess too, but the command is the one the *repository*
  configured, and the line this draws is who wrote the code that runs.
* **An optional entry counts.** `run_shell_command?` is a manifest that permits
  running shell commands; whether the gate applies must not depend on what a
  server happened to advertise this morning, or one file is governed on one host
  and ungoverned on the next.
* **Declaring it is half. Getting it is the other half.** At mission time the
  resolve is told what the `ToolBus` is actually isolating with; a manifest that
  says `bwrap` and gets a bus running `none` — bwrap not installed, or the sandbox
  opted out of — is refused, because a manifest that asked for isolation and did
  not get it asked for nothing. A library caller that resolves without naming a
  bus is not told anything about isolation: unstated is not `none`.
* **`sandbox: none`** is the explicit *no isolation was asked for*. Accepted and
  inert for a manifest with no code-plane tool; refused, with that value quoted
  back, for one that has them. Any other value is refused when the file loads —
  `sandbox: firejail` asks for isolation this framework has no backend for, and
  reading it as good enough is how a declaration becomes decoration.
* It is **rendered into the prompt** (`Sandbox: bwrap`) like any other operational
  field, and unlike the structural keys. Network is denied inside the namespace,
  and an agent that has not been told reads `ENETUNREACH` as a broken tool and
  spends a turn retrying it.

### Without a manifest

`--skill` is optional and you should treat it as mandatory. With no manifest the
mission is **offered every discovered tool** and **builds no grounding
validator**, so the fabrication check that exists for exactly this surface never
runs. The CLI prints a yellow warning saying so; that warning is the only thing
between a deployment and an ungoverned mission whose transcript looks identical
to a governed one. It is a fallback, not a default posture.

The same trap has a second face: `pip install 'judais-lobi[mcp]'` gives you a
*runnable* mission and a *silently ungoverned* one, because `--skill` reads YAML
frontmatter and with no `pyyaml` the manifest never loads. Install `[mission]`.

### The results store

A tool result is capped at 32 KB (`MAX_RESULT_BYTES` in `core/bounding.py`, the
one owner of both the number and the cut) before it enters the transcript — head
and tail with an explicit marker. The **whole** result stays in
a per-mission store under a short handle, and the model can ask for one field:

```
mission_result(handle="r1", path="result.actors[0].score")
```

A few dozen bytes instead of two hundred kilobytes. The store holds no capability
of its own: every byte in it arrived through a dispatch that was already gated,
audited and inside the closed set, so reading it back is not a widening. It is
registered on the bus for the length of one run and withdrawn after it. A
consumer sees the handle on every `tool_result` record, and `tool_result.output`
carries the result **whole** — the bound is what the *model* is shown, not what a
watcher is.

### Gates

`--gate-tool NAME` (repeatable) names a tool this deployment **offers and gates**.
It appears in the catalogue, marked. If the model names it, the call is **not
made**: the mission emits `gate_requested` with the proposed arguments verbatim
and ends at outcome `awaiting_approval` (`core.runtime.mission.AWAITING_APPROVAL`).

The arguments travel verbatim because what a person approves has to be the bytes
that would run.

**No flag on a mission run answers a gate.** A framework that could approve its
own proposal would be a framework whose gate is a formality, and there is no
code path in `MissionRunner` or `SwarmRunner` that can move a record to
*approved* — a test greps for it.

The answer arrives instead as a **durable record written from outside the run**.
Unless `JUDAIS_LOBI_APPROVALS` says otherwise, a gate writes
`.judais-lobi/approvals/<id>.json` holding the tool, the arguments verbatim, the
objective and the run that asked, and the id rides `gate_requested.approval_id`.
Two ways to answer it:

* **A platform calls the library.** `core.runtime.approvals.ApprovalStore(root)`
  → `.get(id)`, `.decide(id, approve=…, decided_by=…, note=…)`, `.pending()`,
  `.reconcile(live_run_ids)`. This is the integration point, and it is why
  `--approve`/`--refuse` are **not** in `contract.CLI_FLAGS`: a platform decides
  in its own process, where it knows who the person is.
* **An operator runs the command.** `judais --mission --approve <id>
  --decided-by <who> [--note …]`, or `--refuse`. It builds no agent and asks no
  model.

`decided_by` is free text and only its **emptiness** is refused. This framework
has no principal system and will not invent one: *who counts as a person* is the
platform's question, and the platform's answer belongs on top of this mechanism
rather than inside it. TAIPAN's `mission/approvals.py` is exactly that — the
same states and transitions with a `must_be_a_person` check that refuses a
delegated agent identity.

The platform then resumes by spawning a *new* mission with `--approval <id>`
(env `MISSION_APPROVAL`), which widens the closed set by exactly one tool, for
exactly one run, after exactly one person said so. The approval is **spent when
the tool is dispatched**, so a resumed run that never reaches it leaves the
decision unspent rather than burning it on nothing; a pending, refused, spent or
abandoned record is refused at the door, naming the state. Nothing defaults or
expires into a yes, and no state anywhere says "this analyst approves
cancellations".

**Read the widening off `mission_started.gated`.** There is no field announcing
an approval on the stream — the approved tool is simply not in the gated list
for that run, which is already the statement of what the run will not call.
Keep passing the full `--gate-tool` list on the resumed spawn; `--approval` does
the subtraction, and doing it yourself as well would make the flag's narrowness
your bug to maintain.

> **A gate name resolves the way a manifest's does, and an unresolvable one is
> a refusal.** `--gate-tool` goes through `_resolve_gates` (`core/cli.py`), which
> asks the same `same_tool` question `SkillManifest.resolve` asks — so a platform
> may pass the wire spelling off its own tool table (`compute_cancel_job`) and
> the bridge's namespaced name (`mcp.compute_cancel_job`) matches it. Either
> spelling works, and the resolved name is what the `🔒 gated:` line prints and
> what the loop enforces.
>
> A name that matches **nothing** is a `SystemExit` naming it and listing every
> tool that *was* offered; a name that matches **two** is a refusal asking you to
> name the namespace rather than a coin flip. Neither is dropped quietly, and
> that is the fix for a real bug. Exact membership (`name in tool_names`) was
> the rule until `_resolve_gates` replaced it: every gate TAIPAN passed in its
> own spelling matched nothing, the `🔒 gated:` line never printed, and the call
> somebody was meant to approve was dispatched like any other. This paragraph
> described the old behaviour for several releases after it stopped being true,
> which is its own lesson about a doc that states a matching rule twice.

### The rest of the CLI

Mission mode is a closed surface: `contract.CLI_FLAGS` and `contract.ENV_VARS`
are what a consumer may rely on, and there is a test that says the parser takes
every one. Everything else in `judais --help` is a *person's* surface and may
move between releases.

---

## Driving it

### The spawn

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

A resumed turn is the same line with `--resume <run-id>` and **no objective**:
the recorded run holds it, and passing a different one is refused.

with `MCP_TOKEN`, `MCP_CLIENT_NAME`, `ELF_PERSONALITY`, `LOCAL_API_BASE` and
`LOCAL_MODEL` in the environment. The objective is a positional argument.

**State the provider and the model.** Both have defaults and both defaults fail
silently in a different way. With neither set on TAIPAN's first production
message, the harness fell through to its hosted OpenAI backend and died on
`Missing credentials` — a turn that reads as a broken agent and is a backend
nobody meant to select. `--provider local` is never fallen back *away* from when
a key is missing, deliberately: asking for the endpoint on this host and being
answered by OpenAI is the opposite of what was asked, and for a mission prompt it
would send the prompt off the host.

A platform pointing this framework at Anthropic sets `ELF_PROVIDER=anthropic`
(or `--provider anthropic`) plus `ANTHROPIC_API_KEY`, installs
`judais-lobi[anthropic]`, and reads `capabilities.supports_json_mode == False` —
constrain output with `tools` + `tool_choice="required"` under `--protocol
native`, not with `response_format`. Like `local`, `anthropic` is never fallen
back away from. The default model is `claude-opus-5`.

`--mission-steps` defaults to **8**, and it counts parse-error turns as well as
tool turns. TAIPAN runs at 24, after a mission was graded as an agent that "stops
dead" when it had simply run out of room.

### Two channels, and only one of them is yours

**stdout is prose for a person** — panels, emoji, the transcript printed after the
fact. It is not a machine channel and a consumer must not parse it. It changes
whenever somebody improves the console rendering, which is as often as somebody
improves the console rendering.

**The event sink is the only machine channel.** `--events` takes three forms:

| form | goes to | for |
| --- | --- | --- |
| `-` | stdout | a person with `jq` |
| `fd:N` | an inherited descriptor | **a harness** |
| *path* | a file, opened for append | a reader that arrives late |

A consumer uses `fd:` or a path, never `-`, so the rendering and the records never
share bytes. `fd:N` is what TAIPAN uses: it opens a pipe, passes the write end
through `pass_fds`, and each line arrives the moment it happens with no file to
tail.

The record vocabulary — ten event types, their required fields, the optional
ones, the five outcome words, and the exit contract — is **`CONTRACT.md`**, and
its authority is `core/runtime/contract.py`. Read those rather than this section;
a summary of a contract is a second copy of it.

### The opening frame is the run's posture

`mission_started` is the one record a driver should read in full before it
renders anything, because five optional fields on it say what kind of run this
is. All five are read with a default.

| field | what a driver does with it |
| --- | --- |
| `sandbox` | `"bwrap"` or `"none"` — the isolation the tool **subprocesses** ran under. Show it. A pane that cannot say whether a shell ran isolated cannot answer the only question an operator will ask about it |
| `profile` | `safe` \| `dev` \| `ops` \| `god` — the capability profile. A `safe` mission and a `god` one are otherwise indistinguishable on the wire |
| `audit_ref` | the path of this process's append-only audit file, or **`null`** when `JUDAIS_LOBI_AUDIT` was set to `none` or `off`. The null is the point: no file and no field are different facts |
| `run_id` | the durable transcript — see below. **Absent**, not null, when nothing is being recorded |
| `protocol` | `"native"`, and **absent** on a `json` run. Absence is what keeps every stream recorded before the field existed byte-identical |

**`sandbox` describes the subprocess plane only.** A bridged MCP tool is
dispatched **in this process** — an HTTP or stdio call out of the harness — and
touches no sandbox whatever this field says. So `sandbox: "none"` is not a
finding for an MCP-only agent, and a platform whose whole tool plane is MCP can
run without bubblewrap and lose nothing. The moment the closed tool set contains
a **code-plane** tool — a shell, an interpreter, a `pip install` — the manifest
must declare `sandbox: bwrap` *and* the run must actually get it, or the resolve
refuses at the door. Those are the two different situations, and only the second
needs bwrap on the host.

### The run store, and picking a killed run back up

`mission_started.run_id` names a directory under `.judais-lobi/runs/<run-id>/`
in the harness's working directory — moved by `JUDAIS_LOBI_RUNS=<path>`, kept
nowhere by `JUDAIS_LOBI_RUNS=none|off`, in which case the field is absent. It
holds an fsync'd, append-only `events.jsonl` of `{seq, at, record}` envelopes and
a `meta.json` replaced atomically. **Every record is appended there before it
reaches the `--events` sink**, so the sink is a client of the log and not a
second copy: a pane that lost the pipe can read the same bytes off disk.

Two more files live beside it, under the same variable, so a platform knows what
its run directory actually contains: **`model.jsonl`** — one fsync'd line per
model call, in call order, with the request (`messages` and the rest of what
went out), the reply, and the `tool_calls`/`usage` side channels read off the
backend — and **`tools.jsonl`**, the tool plane as this run met it: line one the
catalogue (`"call": 0`), every line after it one dispatch with its arguments and
its result, including the MCP `structuredContent` that never travelled on the
event stream. **They are scrubbed less than the event log: credentials only.**
`core.redact.scrub_record` takes five families out of a record on its way to a
pane; here only `scrub_secrets` runs, because absolute paths and this host's
name are *the model's input*, and a recording whose input was rewritten is a
recording of a prompt nobody ever sent. A credential is never written down in
this directory whichever file it arrived in — `MCP_TOKEN` is a transport header
and reaches no prompt, so removing it cannot change the request.

That is what makes them worth keeping: `judais --mission --replay <run-id>`
(env `MISSION_REPLAY`) runs a finished mission **again** out of its own
recording — the real `MissionRunner`, the real grounding validator, replies
served by ordinal and tool results off disk, so no server is dialled and no
model is asked — into a **new** run directory carrying `replay_of` and any
prompt `drift`, which is how a platform scores a grounding change on last
week's runs on a laptop. It is not `--resume`: that continues an unfinished run
against a live model. See `EVAL.md` §10.

For a driver that means three things it could not do before:

* **Answer "did that run ever finish?"** A log whose records include
  `mission_finished` is a run that closed; one without is an orphan. Every
  mission reconciles orphans on the way in — a run untouched for 60 seconds with
  no `mission_finished` gets one appended — so a follower's stream ends rather
  than stopping mid-sentence.
* **Join late.** `RunStore.since(cursor)` and `follow(cursor, stop=…)` replay
  from a `seq`. `seq` is the store's numbering and never travels on the wire.
* **Resume.** `judais --mission --resume <run-id>` with **no objective** —
  it comes off the record, and a different one is refused naming both. The
  records go on being appended to the *same* directory and there is **no second
  `mission_started`**; the first new `step_started` carries
  `resumed: {from_seq, steps_replayed}` instead, which is the frame a follower
  holding a cursor will actually receive.

  A run that ended `answered`, `answered_with_caveat` or `budget_exhausted` is
  refused: those are conclusions. `incomplete`, `awaiting_approval` and a log
  with no ending at all are resumable. A **staged** (`--swarm`) run is refused
  today, and the refusal names the steps that are done. `max_steps` counts the
  whole run, so killing and resuming cannot buy extra steps; passing
  `--mission-steps` on the resumed spawn asks for that many *further* ones. The
  credential is deliberately not persisted — `MCP_TOKEN` is read from the
  resuming process's own environment.

### Bounding a run, and stopping one

`--mission-seconds` (env `MISSION_SECONDS`) is the wall clock, and **unset means
unbounded** — steps bound the work, seconds bound the waiting. It is checked
between steps and before each model call, and one clock covers the whole of a
`--swarm` turn; a call already in flight is not interrupted, so the real bound is
this plus one round trip.

Running out is `outcome: "budget_exhausted"` with `budget: {which, limit, spent}`
on `mission_finished` — present **exactly when** that outcome is, so a driver may
branch on the outcome and index the field. `which` is `steps`, `seconds`,
`bytes` or `tokens`; the last two are declared and not yet emitted. `spent` is
not always `limit`, because a wall clock is noticed a little after it runs out.

Stopping is not an outcome word. A cancelled run — `SIGTERM`, or
`{"control": "cancel"}` — ends `incomplete` with `reason: "cancelled"`, and a
driver that ignores `reason` renders it exactly as it rendered one before the
field existed. `elapsed_s` rides every `mission_finished` this harness emits and
is deliberately **not** inside `usage`, which is absent when the provider
reported nothing while elapsed time is known regardless.

### `--control` — the channel into a running mission

`--events` is what a mission says; `--control` is what it can be told, and until
it existed the only lever on a running turn was `SIGTERM`. It takes the same
forms as `--events` in reverse: `fd:N` (what a platform uses — keep the *write*
end of a pipe and the mission never has a path on disk to race anybody for), a
FIFO, a path, or `-` for stdin. One JSON object per line; the vocabulary is
closed (`core/runtime/control.py`, `COMMANDS`).

Map a platform's controls onto it like this:

| the UI affordance | the command | what happens |
| --- | --- | --- |
| "steer it" / a message typed at a running turn | `{"control": "inject", "text": "…"}` | appended as a `user` turn immediately before the next model call, and reported back as `step_started.injected: ["…"]` — the only trace on the stream that anybody spoke |
| "skip this" / an interrupt that is not a stop | `{"control": "cancel_step"}` | the calls of the current step that have not been dispatched are skipped, the model is told in as many words and asked again. **A tool already running is never killed.** An ask that arrives too late is a no-op and says so |
| "stop" | `{"control": "cancel"}`, then `SIGTERM` if the process must go | the mission winds up at its next check, keeps its transcript, and writes its own `mission_finished` (`incomplete` + `reason: "cancelled"`). The process exits *normally* — a platform asked the mission to stop, not the process to die of a signal nobody sent. `SIGTERM` is the same thing by another road, with the signal's exit status; a **second** `SIGTERM` does not wait |
| an approvals UI, while the run is standing at the gate | `{"control": "gate_decision", "approval_id": "ap_…", "approve": true, "decided_by": "dana", "note": ""}` | the gated call is dispatched **in that same step** and the mission carries on; the record is written through the same `ApprovalStore` the `--approval` path reads, `decided` then `spent`, by the name you sent. A no is recorded as a refusal and the model is told |

With a channel open a gate **waits** rather than ending the run: bounded by
`min(what is left of --mission-seconds, GATE_WAIT_S)`, which is 300 s
(`core/runtime/control.py`). So a driver may now see a `gate_requested` followed,
under the same `index`, by the `tool_call`/`tool_result` for the call it asked
about. **Nothing times out into a yes**: the wait running out ends the mission at
`awaiting_approval` exactly as it always did, with the record left `pending` for
`--approval` on a later turn. `decided_by` must name somebody — this framework
has no identity layer and will not invent one, and a command signed by nobody is
dropped.

A malformed line, an unknown word, an `inject` with no text or a decision signed
by nobody is dropped with **one** sentence on stderr and the run carries on; a
channel nobody writes to, or whose writer goes away, is not an error. **Commands
are not events**: the run answers them by doing the thing.

On `--swarm` there is one channel for the turn, shared the way the wall clock is,
and it reaches the sub-mission that is running.

### Streamed answers — render them, then replace them

Streaming is **on** by default wherever the backend declares
`supports_streaming`. The answer's own fragments arrive as `answer_delta`
records — `index`, `part` (0-based, restarting at 0 for every model call) and
`text` — decoded out of the half-arrived reply at the source.

The rule for a pane is one sentence: **render the fragments as they land and
replace the lot with `answer.text` when the `answer` record arrives.** That
record is always emitted, never suppressed because the deltas added up to the
same string, and only it has been through the grounding path that may append a
caveat. Key provisional text by `index` and clear it on the next `step_started`:
a turn whose reply was rejected leaves fragments behind that no `answer` will
replace. Fragments are scrubbed per fragment, so a credential split across two of
them is not recognisable in either half — display them, keep the `answer`.

**Zero of them is normal** and needs no special case: `--no-stream`,
`MISSION_STREAM=off`, a backend that does not stream, or a turn that called a
tool instead of answering all produce an `answer` with no deltas before it, which
is exactly the stream every consumer read before this event existed.

### `--protocol native`, and what the pane sees

Default is `json` and stays there until the eval harness scores the two
(`ROADMAP.md` §2.5). Under `--protocol native` (env `MISSION_PROTOCOL`) the
request declares the mission's tools as functions plus a synthetic
`mission_answer(text)` and asks for `tool_choice=required` with
`parallel_tool_calls=true`, so an unparseable reply and a tool name nobody offers
become unrepresentable rather than caught a turn later. It is refused at the door
on a backend that does not declare both `supports_tool_calls` and
`supports_tool_choice_required`.

Exactly one thing changes on the wire, and a driver that does not handle it will
render a turn wrong: **one model turn may produce several
`tool_call`/`tool_result` pairs under one `index`**, told apart by the `call`
ordinal — absent on the first call and absent for every call of a `json` run.
`index` still numbers the *model turn* and is still what `--mission-steps`
counts. A call the harness refused before dispatching it still uses up its
ordinal, so a gap in `call` is a refusal and not a lost record, and `usage` rides
the **first** record of a turn only. A gated tool ends the turn on that call: the
calls before it have run, the ones after it are not dispatched, and
`gate_requested.reason` says how many.

Arguments are checked against each tool's own JSON Schema before dispatch in
**both** protocols (`core/runtime/schema_check.py`; `jsonschema` when `[mission]`
is installed, a `required`/`type`/`enum` floor when it is not). A violation is a
`reply_rejected` naming the tool, the field and the rule.

### Metering a run

`mission_finished` carries an optional `usage` field —
`{prompt_tokens, completion_tokens, total_tokens, calls}` — and the three
records that follow a model call (`tool_call`, `answer`, `reply_rejected`)
carry that one call's. It is **what the provider said**, never an estimate, and
it is **absent rather than zero** when the provider said nothing, which local
endpoints routinely do. A platform that bills from it must read it with a
default and must not read a missing field as free. `CONTRACT.md` is the
authority on the shape.

Cost is the platform's to configure, because the framework cannot know it.
A `pricing:` block in the project's `.judais-lobi.yml` adds
`cost: {amount, currency}` inside the `mission_finished` form:

```yaml
pricing:
  openai:
    gpt-4o-mini: {prompt_per_1k: 0.15, completion_per_1k: 0.6}
  local:
    my-served-model: {prompt_per_1k: 0.002, completion_per_1k: 0.002, currency: EUR}
```

Keys are the provider (`openai`, `mistral`, `local`) and the model name as it
was asked for, with `"*"` under a provider covering whatever else it serves.
No block is the normal case: the ledger then carries tokens and no `cost` key
at all, and `local` in particular has no cost until somebody prices it. This
repo ships no price list and never will — prices move, they differ per account,
and a wrong number is worse than none because somebody bills from it.

### AG-UI, if the platform's frontend speaks it

`core/runtime/agui.py` turns these records into AG-UI event frames. It is
**optional and import-free** — dicts only, no AG-UI SDK, and nothing in this
repo imports it — so it costs a deployment that does not want it nothing at
all. Two entry points:

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
and a live pane are one code path. The mapping:

| record | frames |
| --- | --- |
| `mission_started` | `RUN_STARTED` + `CUSTOM mission.opening` (the posture) |
| `step_started` | `STEP_STARTED`, and a `CUSTOM mission.<field>` per optional field (`compacted`, `resumed`, `plan`, …) |
| `reply_rejected` | `CUSTOM mission.reply_rejected`, `mechanics: true` — **never** a `TEXT_MESSAGE` |
| `tool_call` | `TOOL_CALL_START` + `TOOL_CALL_ARGS` |
| `tool_result` | `TOOL_CALL_END` + `TOOL_CALL_RESULT` (output verbatim) |
| `gate_requested` | `CUSTOM mission.gate_requested` (arguments verbatim) |
| `answer_delta` | `TEXT_MESSAGE_START` (on the first one of a step) + one `TEXT_MESSAGE_CONTENT` per fragment, relayed as they arrive |
| `answer` | `TEXT_MESSAGE_END` + `CUSTOM mission.answer` when deltas were relayed; `TEXT_MESSAGE_START` / `CONTENT`×N / `END` + `CUSTOM mission.answer` when they were not |
| `grounding` | `CUSTOM mission.grounding`, carrying the `messageId` it judges |
| `mission_finished` | `RUN_FINISHED`, or `RUN_ERROR` — see below |
| anything else | dropped, per the compatibility rule |

Three behaviours are the point of the module rather than incidental to it, and
a platform writing its own translator should copy them:

* **A rejected reply is mechanics, not content.** The loop's correction prompt
  rendered as prose reads as the agent saying something incoherent. It goes out
  marked, and whether to buffer the rejections and flush them only for a turn
  that ended without an answer is the platform's policy.
* **The grounding verdict rides the answer's own frames** — inline on every
  `TEXT_MESSAGE_CONTENT` and on `mission.grounding` as the `messageId` of the
  message it judges, so a renderer badges the answer rather than drawing a
  sibling a reconnect can separate from it. An interim `repairing: true` report
  is emitted and does **not** close the message.
* **One answer, several bounded frames.** When the harness emits `answer_delta`
  records the deltas are relayed as they arrive and the `answer` record is the
  authoritative replacement — `CUSTOM mission.answer` carries the whole text and
  a reader replaces what it accumulated. When it does not, the module fans the
  text out itself with `answer_deltas`, which splits at line boundaries and never
  inside a fence, so the incremental path is exercised on every run and the
  frames a pane sees are the same shape either way.

**`RUN_ERROR` versus `RUN_FINISHED`.** `incomplete` with **no** `reason` is a
crash — the record comes out of a `finally` holding the outcome nothing got
round to setting — and becomes `RUN_ERROR`; the diagnostic is the tail of
stderr. `incomplete` **with** a reason is `RUN_FINISHED` (plus `cancelled:
true` when somebody pressed stop), because rendering a person's own decision as
a failure tells them something went wrong with the thing they asked for. Every
other outcome, `budget_exhausted` included, finishes.

### Pinning the contract

```python
from core.runtime import contract

assert contract.SCHEMA_VERSION == 1        # fails at import, which is cheap

problems = contract.conforms(record)       # [] when the record is fine
```

`conforms` is pure and standard library only, and imports nothing this repo owns
— a consumer that cannot import an agent framework (a served tier, say) can
vendor that one file and have the whole seam. It checks that the record names a
declared event, that every required field is present, and that any
`schema_version` it carries is one the contract understands. It does not check
types and does not object to extra keys, because an added optional field is a
minor change and a checker that failed on one would make every additive release a
breaking one.

**Drop record types you do not know.** Assert your ignorance in a test rather
than in production: TAIPAN's `bridge.READS` is a frozenset with a test that fails
when this repo declares something new, which is how "no opinion" stays a decision
somebody made rather than a frame nobody noticed.

### `--history`

A JSON file: an array of `{"role": "user"|"assistant", "content": "…"}`, oldest
first. `system` is refused — system text belongs to the harness — and so are tool
turns, which are this mission's own to make. Caps: 100 turns, 262 144 characters.
A malformed history is a refusal at the door, never a silent drop, because a
dropped history is the bug this flag fixes wearing a different hat.

A file rather than an argument, for the same reason `--mcp-token` prefers the
environment: a conversation is many kilobytes and argv is world-readable.

**A caller passing `--history` must not also fold the history into the
objective.** The turns are seeded as *real role-tagged chat messages* ahead of
the objective. A chat-tuned model attends to those and skims past the same text
pasted into the message: measured 12 August 2026, "tell me more about #2"
web-searched `#2` literally while the list sat two lines up in the prompt.

### The exit contract, in six lines

* **Zero events is a failure.** `mission_started` is emitted before the model is
  asked and before the tool plane is touched — before the *first* call, which
  under `--swarm` is the router's own and not the first step's — so an empty
  stream means the harness never got that far: a cold model server, a refused
  token, an unreachable endpoint. It is never an empty answer. Report it as a
  failure rather than rendering a blank reply.
* **`mission_finished` always arrives.** It comes out of a `finally`, so a
  mission killed by an exception still closes its own stream; it closes it
  holding `incomplete`, which reads as "stopped, and the reason is on stderr".
* **SIGTERM asks a run to wind up, and it gets to.** The first signal throws the
  mission's cancellation: the loop stops at its next step, keeps its transcript,
  and writes its own `mission_finished` — `incomplete` with
  `reason: "cancelled"` — and only then is the sink flushed and closed. So a
  stopped turn closes its stream with the record that says it is over rather than
  with the record before it. The default disposition is then restored and the
  signal re-raised, so the exit status is still the signal's rather than a
  spurious clean exit. A **second** SIGTERM does not wait: it flushes, closes and
  dies, so a run stuck in a model call can still be stopped.
* **`--control` is the only channel in**, and nothing on it is an event. One
  JSON object per line: `inject`, `cancel`, `cancel_step`, `gate_decision`. A
  malformed line, an unknown word or a decision signed by nobody is dropped with
  one sentence on stderr and the run carries on; a channel nobody writes to is
  not an error. `step_started.injected` is the only trace on the stream.
* **A run leaves a directory.** `mission_started.run_id` names it, and under
  the harness's `.judais-lobi/runs/<run-id>/` there is an fsync'd append-only
  `events.jsonl` holding every record that went on the stream — appended
  *before* the sink saw it, so the sink is a client of the log rather than a
  second copy. Each line is a `{seq, at, record}` envelope; `seq` is monotonic
  per run and is the cursor a replay resumes from, and the record inside is
  byte-identical to what came off the pipe. A log without a `mission_finished`
  is an orphan: a mission that died rather than one that answered. The field is
  **absent** when `JUDAIS_LOBI_RUNS=none|off` told the harness to keep nothing,
  and `JUDAIS_LOBI_RUNS=<path>` moves the directories somewhere a platform can
  collect them. No credential is written there — not `MCP_TOKEN`, and not a
  transport that might carry one in a URL or a command line.
* **stderr carries the diagnostic**, and its tail is what to show when a mission
  produced no events or stopped without an answer. It is a traceback, and the
  harness **scrubs it before writing it** — home directories, that host's name,
  credentials held in its environment and absolute frame paths become `<home>`,
  `<host>`, `<cwd>`, `<site-packages>`, `<stdlib>` and `<redacted:NAME>`, by the
  same `core.redact` pass that every free-text field on the stream goes through.
  A platform may show it to somebody who is not an operator, and does not need a
  location sweep of its own. `tool_result.output` and `arguments` are
  deliberately left alone: they are the evidence and the call.

### Your own eval suite

A mission is a question about a deployment's data, and this framework has none —
so a platform keeps its suite **in its own repository**, as YAML or JSON, the
same way it keeps its personalities and its skills. Nothing in `core/eval/` knows
a tool name, an asset id or a deployment.

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

```
python -m core.eval check --suite path/to/suite.yml
python -m core.eval run   --suite path/to/suite.yml --out DIR -- <your spawn line>
python -m core.eval score --suite path/to/suite.yml --runs DIR
```

Three things to know before writing one, all of them things the reference
deployment got wrong first:

* **The split is mechanical, not a judgement.** `split: test` is held out, and
  the report never blends the halves. A suite tuned against the half it is
  scored on measures the tuning.
* **`tools:` and `assets:` are what make a suite checkable.** `check` refuses a
  suite whose mission expects a tool the plane does not have or whose prompt
  names data the platform does not hold — TAIPAN shipped a `disambiguation`
  mission that was quietly measuring `absence` for a month, and marked an agent
  FAIL against a question it could not have answered.
* **The spawn line after `--` is yours.** Provider, model, tool plane, skill,
  protocol — those are the variables being measured, and a harness with opinions
  about them would be measuring itself. The harness adds exactly three things:
  the objective, `--events fd:N`, and `JUDAIS_LOBI_RUNS` pointed inside the
  mission's own directory.

`score` needs no GPU and no server: it reads run directories that already exist,
so a platform scores its own archive, and `--replay` on those recorded run
directories is how a change to a `grounding:` block is measured on runs the
platform already has. The whole guide is **`EVAL.md`**; §9 is the suite format.

---

---

## Releasing and pinning

### Cutting a release

1. Bump `VERSION` in `setup.py`. That constant is what `pip` reports, and it is
   what a platform's deploy doctor compares its checked-out tag against.
2. Update the version in `setup.py`'s `description` string and in `README.md`'s
   status line — both are typed rather than derived, and
   `tests/test_docs_track_the_code.py` holds the README against `VERSION`.
3. Tag `vX.Y.Z` and push the tag.

### How a platform pins one

One file, one line, one git tag, and nothing else in the platform states the
version. TAIPAN's is `deploy/JUDAIS_LOBI_VERSION`, holding one tag of this
repo; `scripts/deploy_judais_lobi.sh` checks that tag out on the pool as a
**detached git checkout** — not an rsync — and runs `pip install -e '.[mission]'`
into a named venv, then restarts the pane and reports what is there.

The checkout is the point. The pool's copy used to arrive by rsync, and an
rsynced directory has no version: `git describe` had nothing to describe and
`pip show` reported whatever was installed last, so "which harness answered that
mission" could only be answered by reading code on the host. A pin nobody can
verify on the host is a pin in name only, and the deploy script's `doctor`
subcommand exists to answer that question in one command.

### The compatibility rule

`SCHEMA_VERSION` is carried on every `mission_started`.

* **Additive is minor.** A new event, or a new *optional* field on an existing
  event, does not bump it. Safe because consumers drop record types they do not
  know.
* **Breaking bumps it.** Renaming a field, removing one, moving one out of the
  required set, or changing what an existing required field means. A consumer
  that pins `contract.SCHEMA_VERSION == 1` finds out at import, which is the only
  moment at which finding out is cheap.

### Testing a new release against a platform

**A new judais-lobi release is tested by this sequence and by nothing else:**

1. On a branch in the *platform's* repository, bump the pin file to the new tag.
2. Run the platform's tests that cross the seam — the ones that hold its
   restatement of the event vocabulary against a checkout of the new tag. A
   served tier cannot import an agent framework, so its bridge restates the field
   names as literals, and those tests are the only thing standing between a
   renamed field and a pane that renders a turn with the content silently
   missing. TAIPAN runs `test_mission_bridge.py`, `test_mission_service.py` and
   `test_judais_lobi_pin.py`.
3. Deploy to a staging pane and drive one real mission through it. The
   consumer-side conformance check is not the same thing as an agent that
   actually answered.
4. Have the deployment report which tag it is on, and whether the version `pip`
   reports agrees with it.

---

## Python floor

**3.10** (`setup.py`, `python_requires=">=3.10"`). The reference deployment runs
3.10. Two consequences worth knowing:

* `tomllib` is 3.11+. On 3.10 a TOML personality needs `pip install tomli`; the
  loader tries `tomllib`, then `tomli`, then refuses with that sentence.
* Every optional stack is an **extra**, not a requirement: `[mission]` (`mcp` +
  `pyyaml` + `jsonschema` — what a mission actually needs; without `jsonschema`
  the pre-dispatch argument check falls back to a top-level
  `required`/`type`/`enum` floor), `[mcp]`, `[critic]`, `[faiss]`,
  `[treesitter]`, `[voice]`, `[dev]`. A plain install must stay small enough that
  `judais --help` works without any of them.

---

## What must never enter the framework

judais-lobi drives whatever platform it is pointed at. Four things had stopped
believing that, each one shipped inside the package, and each was removed in
`c54eb3d`. They are listed here as a shape to recognise, not as history:

* **A platform's paths.** A personality search that tried
  `~/data/workspace/TAIPAN`, `~/workspace/TAIPAN` and `../TAIPAN`, with another
  repository's source layout frozen into a constant. That is one developer's
  laptop, installed onto every other machine.
* **A platform's SDK name.** `import taipan`, written into a swarm rung sentence
  under a comment promising that a role never names a platform's particulars. It
  is a manifest field now (`sdk_import`).
* **A live hostname or a real credential variable in `--help`.** An example is
  copied before it is read. A hostname in `--help` is a hostname published to
  everyone who ever runs `--help`, and a token named in argv is a token visible
  in `ps`.
* **Absolute paths in tests.** Two suites were anchored to artifacts on one
  machine and skipped everywhere else, silently, with nothing telling anyone how
  to opt in. They read `TAIPAN_SKILLS_DIR` and `TAI_RECORDINGS_DIR` now and skip
  with a sentence naming the variable.

And the general form, which is the only one worth memorising:

* **A platform's tool names**, anywhere outside a manifest. The bus's catalogue
  is the one description of a tool; a second copy disagrees with the first the
  day a server changes a description.
* **A personality as a default.** The framework ships no personality it does not
  contain, and it does not invent one. A missing personality is a refusal that
  names what was consulted, not an agent running on whatever it was handed while
  still calling itself by the right name.
