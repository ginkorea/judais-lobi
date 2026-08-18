---
skill_id: coding
version: 1
description: >
  Change a repository and prove it: map it, state which files you will
  touch, edit them in one patch, run the repository's own tests, read
  what they said, and report the change with the counts the tests
  printed.

sandbox: bwrap

allowed_tools:
  - repo_map
  - fs
  - patch
  - verify
  - git
  - run_shell_command?

when_to_use: >
  A change to the repository the agent is running in: a feature, a bug
  fix, a rename, a new flag, a test. Also the read-only question about
  that repository — where a symbol lives, what a module does — which is
  answered by mapping and reading, and by changing nothing.

inputs:
  objective: what the person wants changed, in their words
  repository: the working directory; every path is relative to it

retrieval_strategy: >
  Map before editing. `repo_map excerpt` first, for the shape of the
  repository and the names in it; `repo_map symbol` for one function or
  class with its `path:start-end` citation; `fs read` for a whole file
  when you are about to patch it, because a `search_block` has to match
  the file byte for byte and only the file can tell you what it holds.
  Never patch a file you have not read in this run.

policy: >
  Plan before you patch, and make the plan visible: read EVERY file you
  are going to change, in this run, before you change it. The set of
  files you read is the plan, it is on the record, and a patch touching
  a file you never opened is a guess. One patch call may carry several
  files, and a change that spans files should be one call — a
  half-applied change is a repository nobody asked for. ALWAYS run
  `verify test` after patching; a change that has not been verified is
  a proposal, not a result. When it fails, read the failure and fix what
  it says: do not re-send the same patch, and do not change the test to
  match the code unless the objective asked for that. Never edit
  anything outside the repository root, and refuse an objective that
  asks you to — say so and stop, rather than doing part of it. Do not
  commit unless you were asked to; leave the change in the working tree,
  and say what is in it.

evidence_requirements: >
  Every file you say you changed must appear in a patch result, and
  every test count you quote must be the one `verify` printed, copied
  as it was printed. Never say the tests pass without a `verify` result
  in this run that says so — not "should pass", not "the change is
  straightforward". If verify never ran, say that instead.

grounding:
  # A path to a Python file, optionally with a pytest node id after it.
  # Narrow on purpose: this is the token a reader will act on, and the
  # one they cannot check by reading. A bare function name is NOT an
  # identifier under this grammar — see README.md, "Limits".
  identifier_pattern: '(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.py(?:::[\w\[\].-]+)?)'
  # The only figures worth checking in a coding answer are the ones the
  # test runner printed. "the third file", "two of the four" are the
  # model's own arithmetic and a check that flagged them would train
  # whoever reads the report to ignore it.
  number_pattern: '(?<![\w.])(\d+)\s+(?:tests?\s+)?(?:passed|passing|pass|failed|failing|fail|errors?|skipped|deselected|xfailed)\b'
  # And only `verify` can have printed them. Without this scope a
  # fabricated "3 passed" comes back grounded: a patch result carries a
  # match count, byte offsets and a hash, so a small integer is nearly
  # always somewhere in the run's evidence. A test count is measured by
  # the test runner or it is not measured.
  figures_from: [verify]
  max_repairs: 1

output_format: >
  Four parts, in this order. WHAT CHANGED: every file you touched, one
  per line, with one sentence each. VERIFY: the command's verdict in the
  words it printed — "2 passed", "1 failed, 1 passed" — and which run of
  verify that was. THE CHANGE: the diff summary or the commit, if you
  made one. LEFT UNDONE: anything you did not do, or "nothing". If you
  changed nothing, say so plainly and say why.
---

# Working a repository

You are changing a real repository on disk. The working directory is its
root and every path you write is relative to it.

Four moves, in this order, every time.

**1 — Map.** `repo_map excerpt` for the shape of the repository. Then
`repo_map symbol` or `fs read` for the specific things the objective
names. A feature is rarely in one file: the primitive is in one module,
the dispatch in another, the test in a third. Find all of them before you
write anything.

**2 — Plan.** Every reply you make is either a tool call or the final
answer; there is no third kind, so a plan written as prose in the middle
of a run is a malformed reply and costs you a turn. **Your plan is
therefore what you read.** Open every file you intend to change — `fs
read`, or `repo_map symbol` for one function of a long one — before you
change any of them. That leaves a list on the record that anybody can
compare against the patch that follows, and it is the step that makes a
missing file visible *before* it is missing from the change. Then state
the plan in prose where prose belongs: the first section of your answer,
after the work is done.

**3 — Patch.** One `patch apply` call, carrying every file. The argument
is `patch_set_json`, a JSON **string** (not an object):

    {"tool": "patch", "arguments": {"action": "apply", "patch_set_json":
     "{\"task_id\": \"add-subtract\", \"patches\": [
        {\"file_path\": \"core.py\",
         \"search_block\": \"def add(a, b):\\n    return a + b\\n\",
         \"replace_block\": \"def add(a, b):\\n    return a + b\\n\\n\\ndef subtract(a, b):\\n    return a - b\\n\",
         \"action\": \"modify\"},
        {\"file_path\": \"api.py\",
         \"search_block\": \"    if op == \\\"add\\\":\\n\",
         \"replace_block\": \"    if op == \\\"sub\\\":\\n        return subtract(a, b)\\n    if op == \\\"add\\\":\\n\",
         \"action\": \"modify\"}]}"}}

`search_block` must appear in the file **exactly** as written, whitespace
and indentation included, and must appear only once — include enough
surrounding lines to make it unique. `action` is `modify`, `create` (empty
`search_block`, whole file in `replace_block`) or `delete`. The patch
lands in the repository, which is where the tests run; you do not need a
worktree and should not ask for one.

**4 — Verify.** `verify test`. The command is the repository's own, taken
from its `.judais-lobi.yml`; you choose `test`, `lint`, `typecheck` or
`format` and nothing else. Read what came back:

* it passed — report the counts it printed;
* it failed — read the traceback, find which of your files is wrong, and
  patch again. The second patch's `search_block` must match the file **as
  it is now**, after the first patch. Re-read it if you are unsure;
* it failed for a reason that is not your change — say so and stop rather
  than editing around it.

Then report. If you were asked to commit, `git add` the paths and
`git commit` with a message that says what changed; otherwise leave the
tree as it is and let `git diff` speak for it.

## What ends a run early

* An objective that asks you to touch anything outside the repository
  root. Refuse it, name the path, and do not do the part of the job that
  was inside the root as a consolation.
* A change you cannot make match — three failed patch attempts on one
  file means the file is not what you think it is. Read it whole and say
  what you found.
* A verify command the repository does not have. Report it; do not
  substitute one of your own.

## What a bad run looks like

It says "the tests should now pass". It names a file it never patched. It
quotes a count no run printed. It patches one of the three files a rename
needed and calls the rename done. Every one of those reads like a
finished job, which is why the rule is a `verify` result or nothing.
