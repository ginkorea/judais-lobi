# The `coding` pack

**A tested multi-file coding ability.** Plan, edit across files, verify by
running the repository's own tests, report the change with the counts the
tests printed. This is Phase 15's first mission pack (ROADMAP §2.6b) and the
one that makes "this was not meant to just be a chat agent" a thing the
suite can check rather than a thing the README says.

    core/skills/library/coding/
      SKILL.md              what the model is told and held to
      missions.yaml         eight eval missions, EVAL.md §2 shape
      templates/coding.yaml the task template: plan → patch → verify → report
      fixtures/             four small git-able repositories to run against
      README.md             this file

## What it does

| | |
|---|---|
| closed set | `repo_map`, `fs`, `patch`, `verify`, `git`, `run_shell_command?` |
| profile | `dev` — `fs.write`, `git.write`, `python.exec`, `shell.exec` on top of SAFE |
| isolation | `sandbox: bwrap`, **required** |
| server | none. Every tool is this package's own, registered by `core.tools.Tools` |
| grounding | file paths as identifiers, test counts as figures |

`sandbox: bwrap` is not a preference. `run_shell_command` is in the closed
set, so `SkillManifest.code_plane_entries` sees a tool that runs code the
model composed **on this host**, and the manifest is refused unless it
declares bwrap *and* the bus is running it. That holds even when no shell is
registered — what the gate reads is what the manifest permits, not what a
bus happened to advertise. `verify` is deliberately not one of those tools:
it also ends in a subprocess, but the command belongs to the repository and
the model chooses only which of `lint`/`test`/`typecheck`/`format` to run
(see `core.runtime.skills.CODE_PLANE_SCOPES`).

## Running it

The working directory **is** the repository. `PatchTool`, `RepoMapTool` and
`load_project_config` are all built against a path and `VerifyTool` runs
where the process is, so there is one fact rather than four that can
disagree.

    cd /path/to/your/repository
    judais --mission --profile dev --skill coding \
      "Add a --colour flag and cover it."

`--skill coding` by name: the pack ships in the wheel and
`core.skills.library.resolve` reads a name when nothing exists at that
path. A path to the `SKILL.md` works too and wins if it exists.

No `--mcp-stdio`, no `--mcp-url`: a mission whose closed set is entirely
built-in needs no server, and this pack's is. Add `--events -` to watch the
NDJSON, `--protocol native` to have the tools declared as functions (which
is also the only mode where the argument *descriptions* in
`core/tools/descriptors.py` reach the model).

From Python, through the façade:

    from judais_lobi import Run, Personality, ToolPlane, Bounds, Store, \
        Observer, Model, Tools

`tests/pack_fixtures.py` does exactly that assembly — bus, manifest,
grounding validator, sink — in `coding_bus()` and `drive()`, and is the
worked example.

## How a repository states its verify command

In `.judais-lobi.yml` at the repository root:

```yaml
verification:
  test: "{python} -m pytest -q"
  lint: "ruff check ."
  typecheck: "{python} -m mypy ."
  format: "ruff format --check ."
```

`{python}` expands to the interpreter the agent is running under, quoted.
It exists because the verify command is the one command a *repository*
authors and the agent runs somewhere the repository has never seen — inside
bwrap, out of a wheel in a venv nobody activated, from a pool worker. A bare
`pytest` depends on that venv's `bin` being on `PATH`; under the sandbox
that is whatever `PATH` the parent had, and the failure it produces
(`pytest: command not found`) reads as a broken tool rather than as a
missing declaration. A project whose tests need a *different* interpreter
from the agent's writes it out: `test: ".venv/bin/python -m pytest"`.

A repository that declares nothing still verifies: the defaults are
`{python} -m pytest`, `{python} -m mypy .`, `ruff check .`,
`ruff format --check .`. `fixtures/rename_symbol` ships no config on purpose
and is the test of that path.

## The fixture repositories

Four, small, deterministic, offline. Each is a plain directory — no nested
`.git`, because git does not carry one — and
`tests/pack_fixtures.fixture_repo(name, tmp)` copies it to a temporary
directory, runs `git init`, sets an identity and makes one commit. A test
or a mission gets a clean tree every time.

| fixture | shape | what a mission has to do |
|---|---|---|
| `pkg_two_modules` | `core.py` + `api.py` + `tests/test_api.py` | a feature needs the primitive, the dispatch **and** a case |
| `bug_across_files` | `records.py` + `index.py`, **red on a fresh clone** | the fix is in two files; fixing either alone leaves it red |
| `rename_symbol` | `util.py` + two callers + the test; **no `.judais-lobi.yml`** | one symbol, three usage sites, and the default verify command |
| `add_cli_flag` | `main.py` (argparse) + `handler.py` + `tests/test_cli.py` | a flag is never only a flag |

The copy itself is `Pack.stage_fixtures(dest)` — the loader's own answer to
"get this pack's data somewhere writable", and the reason it is not read
where it lies: a sandboxed run binds its working directory read-WRITE, so a
mission run inside the installed pack would be writing into
`site-packages`. `stage_fixtures` copies a fixture that is a *directory*
with `copytree`; this pack is the one whose fixtures are nothing else.
The `git init` on top of that copy is
`tests/pack_fixtures.fixture_repo(name, tmp)`, which lives in `tests/`
because `tests/` is not in the wheel and four lines of `git config` are
not something a pack needs to ship.

## The eval suite

`missions.yaml`, eight missions, three held out (37.5%, inside
`TEST_SHARE`). Load it with `core.eval.load_suite(path)`.

| key | flag | fixture | split |
|---|---|---|---|
| `feature_two_files` | synthesis | pkg_two_modules | train |
| `fix_bug_across_files` | chaining | bug_across_files | **test** |
| `rename_symbol_everywhere` | orientation | rename_symbol | train |
| `add_cli_flag` | disambiguation | add_cli_flag | train |
| `tests_fail_then_fix` | state | bug_across_files | **test** |
| `no_claim_without_verify` | absence | pkg_two_modules | train |
| `refuse_outside_root` | boundary | pkg_two_modules | **test** |
| `where_is_the_dispatch` | routing | pkg_two_modules | train |

A real recorded stream per mission is committed under
`tests/fixtures/eval/coding/` — a good agent for each, a bad one for each,
and a third for `feature_two_files` that fabricates a file path. Nothing is
hand-written NDJSON: every one came out of `tests/test_pack_coding.py`
driving the real loop, the real bwrap sandbox and a real pytest run inside a
real git checkout, with only the model scripted. Refresh with

    JUDAIS_LOBI_EVAL_FIXTURES=refresh .venv/bin/python -m pytest \
        tests/test_pack_coding.py

and read the diff.

## The three layers, and which one is real here

ROADMAP §2.6b: **skill** (what the model is told), **task** (a workflow
shape with a judge), **campaign** (a DAG of tasks with handoff and
approval).

`SKILL.md` is the first. `templates/coding.yaml` is the second, written as
**data and not yet wired** — it declares intake → plan → implement → verify
→ finalize, the `verify`-fails-goes-back-to-plan branch, and a judge that is
the verify result rather than a second model. Nothing composes those roles
into `Run`s yet: **wiring the template, and the campaign layer above it, is
Phase 15's next lane.** Until then a single `Run` follows the shape because
`SKILL.md` tells it to, and `tests/test_pack_coding.py` holds the two
documents to the same shape so they cannot drift apart while nobody is
looking.

The clearest argument for doing that wiring is in the template beside the
`plan` role: **inside one `Run` there is nowhere for a plan to go.** The
JSON protocol admits two replies — a tool call and the answer — so an agent
that writes its plan as prose mid-run gets `reply_rejected` and loses a
turn. The pack's workaround is to make the plan *observable* instead of
spoken: read every file you are going to change, and the read set is the
plan, on the record, comparable against the patch that follows. It works and
it is a workaround. As a role, `plan` is a `Run` whose answer **is** the
file list, handed on as an artifact.

## Limits

Stated because a pack that overstated these would be worse than one that
did less.

* **The repository root is a prompt-level rule, not an enforced one.**
  `SKILL.md` says never edit outside it and `refuse_outside_root` measures
  whether the agent honours it. Nothing stops it: `FsTool` is pure
  in-process `pathlib`, so bwrap — which isolates *subprocesses* — does not
  see it, and under `dev` the `fs.write` scope is granted for any path the
  user can write. A confinement would be a `root=` on the filesystem tools
  wired from the mission's working directory; it does not exist yet.
* **The figure check cannot catch a plausible count.** A fabricated
  "3 passed" comes back *grounded*: `NumericGroundingCheck` supports a
  figure if it equals any figure anywhere in the run's evidence, and a
  patch result carries match counts and byte offsets, so a small integer is
  nearly always somewhere. What catches it is the machine check EVAL.md
  prescribes — `expects_tools: [verify]`, read off the stream. The
  **identifier** half does bite, and `feature_two_files.invents.jsonl` is
  the committed proof.
* **A bare function name is not an identifier here.** The grammar matches
  Python paths and pytest node ids, so an invented `core/utils.py` is
  refused and an invented `def frobnicate` is not. Narrowing it to catch
  symbol names would flag every true mention of a function the agent was
  reading about.
* **A long test log cannot be read back by section.** A result over
  `MAX_RESULT_BYTES` is bounded head-and-tail with a marker naming its
  store handle, but `mission_result(handle=...)` returns only a *summary*
  for a text-only result — there is no `path` into plain text. The skill
  therefore teaches re-reading the file with `fs read` rather than paging
  the log.
* **The suite grades as a pack's and not as a plane's.**
  `core.eval.check_the_suite_is_gradeable` requires every flag in
  `core.eval.FLAGS` to be captured, which eight coding missions cannot do
  honestly — `submission`, `protocol_shape` and `partial_synthesis` would
  each need a mission written to satisfy a checker. `Pack.suite()` goes
  through `core.skills.library.check_pack_suite`, which is that same check
  with coverage scoped to the flags this suite captures, plus the rule only
  a pack can make (every tool a mission names is in the closed set). That
  scoping is an adapter with a named replacement: what `core/eval/` wants
  is a suite-level `flags:` declaration, after which it goes away. A test
  here asserts both the scoped pass and the unscoped refusal, so the reason
  survives the adapter.
* **The corpus is not in the wheel.** `tests/` is excluded from the
  distribution, so an installed pack ships its manifest, template, missions
  and fixture repositories, and the sixteen recorded transcripts stay in
  the repository as the harness's evidence about the pack.
