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
| `env_path` | no | `~/.elf_env` | where the agent looks for API keys |
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
Capability gating, the panic switch and the audit log apply to it exactly as to a
compiled-in tool. The tool's JSON Schema is carried whole on the descriptor, so
the catalogue the model reads says `type (string: dataset|model|service)` and not
just `type` — types, `required` and enums are what decide whether a *first* call
to a faceted search works.

### The skill manifest

`--skill DIR` (or `--skill DIR/SKILL.md`, or `MISSION_SKILL`) loads one manifest:
YAML frontmatter between `---` fences, then a Markdown body. It needs `pyyaml`,
which is why `[mission]` and not `[mcp]` is the extra to install. Point it at a
directory holding several skills and it refuses, listing them by name.

Four things come out of a manifest and nothing else does.

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

**`grounding` — the identifier grammar.** A mapping, interpreted by
`core/runtime/grounding.py` and never by the loader. Absent means no validator is
built and the transcript's grounding report stays `None` rather than claiming a
clean check: a check that could not run reports *no opinion* and never a pass,
because a fabricated "grounded" is a governance claim. See the README for
`identifier_pattern`, `ignore`, `max_repairs`, `must_cite` and `claim_table`.

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

A tool result is capped at 32 KB (`MAX_RESULT_BYTES`) before it enters the
transcript — head and tail with an explicit marker. The **whole** result stays in
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

**There is deliberately no flag that answers a gate.** A framework that could
approve its own proposal would be a framework whose gate is a formality. The
platform resumes by spawning a *new* mission with the approved tool removed from
its `--gate-tool` list — which widens the closed set by exactly one tool, for
exactly one turn, after exactly one person said so. TAIPAN does precisely that,
and holds no state anywhere saying "this analyst approves cancellations".

> **Name a gated tool the way the resolved catalogue names it.** Unlike
> `allowed_tools`, which matches by `same_tool`, gate names are matched by exact
> membership in the resolved set (`core/cli.py`: `name in tool_names`,
> `MissionRunner._gated`). The resolved set is namespaced, so the name to pass is
> `mcp.compute_cancel_job`, not `compute_cancel_job`. A gate name that matches
> nothing is dropped silently — the `🔒 gated:` line simply does not print, which
> is the only signal you get.

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
       --provider local                 \
       --model    org/model-name        \
       --skill    /path/to/skills/thing \
       --events   fd:7                  \
       --history  /tmp/turn-history.json \
       [--gate-tool mcp.some_tool]…     \
       [--swarm]
```

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

The record vocabulary — nine event types, their required fields, the optional
ones, the five outcome words, and the exit contract — is **`CONTRACT.md`**, and
its authority is `core/runtime/contract.py`. Read those rather than this section;
a summary of a contract is a second copy of it.

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

### The exit contract, in four lines

* **Zero events is a failure.** `mission_started` is emitted before the model is
  asked and before the tool plane is touched, so an empty stream means the
  harness never got that far — a cold model server, a refused token, an
  unreachable endpoint. It is never an empty answer. Report it as a failure
  rather than rendering a blank reply.
* **`mission_finished` always arrives.** It comes out of a `finally`, so a
  mission killed by an exception still closes its own stream; it closes it
  holding `incomplete`, which reads as "stopped, and the reason is on stderr".
* **SIGTERM closes the sink.** Flushed and closed, then the default disposition
  is restored and the signal re-raised — so what was already written survives,
  and the exit status is still the signal's rather than a spurious clean exit. A
  consumer that asked a turn to wind up sees it wound up.
* **stderr carries the diagnostic**, and its tail is what to show when a mission
  produced no events or stopped without an answer. It is a traceback and it
  **carries absolute paths from that host**. Scrub it before anybody but an
  operator sees it.

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
version. TAIPAN's is `deploy/JUDAIS_LOBI_VERSION` (`v0.8.0` at the time of
writing); `scripts/deploy_judais_lobi.sh` checks that tag out on the pool as a
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
* Every optional stack is an **extra**, not a requirement: `[mission]` (the MCP
  client and `pyyaml` — what a mission actually needs), `[mcp]`, `[critic]`,
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
