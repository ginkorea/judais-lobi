# core/runtime/prompts.py — the conduct, as opposed to the syntax

"""The framework's default prompt text: how to work a governed tool plane.

**Why this module exists at all.**  Every deployment of this framework has
written the same paragraph for itself.  The reference deployment wrote it
into its personality; the two shipped packs wrote it into their manifests'
``policy:`` lists; the in-repo eval fixture wrote a third copy into
``tests/fixtures/eval/stub_skill.md``.  Three copies of one fact is the
arrangement ``ROADMAP.md`` §3 calls *one owner per fact*, and it had
already cost this repository once — the swarm hand-listing six grounding
fields where the direct path emitted ten.  ``ROADMAP.md`` §2.8 asks for the
repair: "framework defaults for the prompt text that every deployment has
had to write for itself: how to work a governed tool plane, and 'if a
number is not in the view, it is not in the draft.'"  This is that text.

**Conduct, not syntax, and that is the seam with**
:mod:`core.runtime.mission`.  :data:`~core.runtime.mission.PROTOCOL` and
:data:`~core.runtime.mission.NATIVE_PROTOCOL_TEXT` say how a reply is
*shaped* — one JSON object, or a function call — and they stay there
because the branch that parses a reply and the sentence that asked for it
must not be able to disagree.  Nothing in this module can be parsed.  It
says how to *work*, it is the same under both protocols, and a run under
either one is stacked with the same bytes of it.

**Where each sentence came from.**  Every clause below is a lesson
``ROADMAP.md`` §5.9 or a shipped pack paid for, and none is an opinion:

* *"A refusal names its scope and what would unblock it … never send the
  same call twice unchanged."*  §3, "refusals name the reason and the fix"
  — every refusal the production agent emitted in its demo was read aloud
  as a feature.  The no-retry half is the research pack's ``host_not_allowed``
  clause ("that is a decision, not a fault: do not retry it") generalised
  off HTTP: a governed plane refuses for a reason that a second identical
  call cannot change, and the reference deployment spent turns of a
  59 tok/s budget discovering that.
* *"The catalogue is all there is, and what it does not list you cannot
  do."*  ``PLATFORMS.md`` §4: asked to "use the SDK" on a pane granting no
  code plane, an agent wrote "Using the SDK I accessed…" while calling only
  MCP tools.  The mechanical fix was the ``planes:`` block; this is the
  half a prompt can carry.  It is about **capability**, deliberately not
  about spelling: "use only tool names from the catalogue" is
  :data:`~core.runtime.mission.PROTOCOL`'s sentence and this module does
  not restate it.
* *"Results arrive bounded; the whole of each is in this run's store."*
  §5.9, "three copies of one 33 kB view was a context problem that was not
  about context" — the per-mission result store, and the research pack's
  evidence clause telling the model to walk it by section rather than
  fetch the page again.  It names no tool: the catalogue names the tool,
  once, so a run whose store tool is withheld is not told about a tool it
  has not got.
* *"A failed call is an answer."*  The research pack's "a 404 is an
  answer" and the analyst's missing-file clause, which are the same rule
  about two different planes.
* *"An error whose text names the fix is an instruction … And what
  failed this turn is not what the plane lacks."*  A production
  transcript on the reference deployment (21 Aug 2026): ``run_code``
  failed with an ``AttributeError`` and a detail line saying *"Read
  stderr, fix the code, and call run_code again — files and packages
  persist"* — and the model apologised and pasted the code into the
  answer for the human to run.  Same session, second shape: two
  transport errors and the model concluded "the platform cannot render
  charts" and *remembered* that conclusion across turns.  "A failed call
  is an answer" had landed as "a failed call is a permanent fact about
  the platform" — so the paragraph now carries its own two bounds.  The
  once is load-bearing both ways: it does not contradict "never send the
  same call twice unchanged", because a call with the fix applied is a
  changed call; and a second failure after the fix IS the answer.
* *"If a number is not in the view, it is not in the draft."*  §2.8 asks
  for this sentence by name.  Behind it: §5.9's "write no numbers was a
  winning move against a substring check", the claim table, and the echo
  rule in :mod:`core.runtime.grounding`.  The second half — *spelled as
  the tool spelled it* — is §5.9's "the same tool spelled three ways cost
  two turns and deleted a true sentence".
* *"A figure you derive — a sum, a share, a difference — is one a
  computation tool printed."*  The reference deployment's hard-tier
  regression ``staged_arithmetic`` (18 Aug 2026, run against the 1.0
  candidate): asked for the top-5 share of a run's total "with the working
  shown", the model read the ranking view, did the division in prose and
  wrote a percentage no tool had printed.  The echo rule cannot catch it —
  every *input* figure was in a view — and the analyst pack's own "a
  figure is printed by the computation that produced it" only reaches a
  run under that pack.  The rule is the plane's: when a computation tool
  is offered, arithmetic is its job; when none is, the working is shown
  from figures the tools returned, which is a reproducible sentence
  rather than an asserted one.
* *"When the request points at something the plane can list … look it up
  before you ask."*  The same suite's ``gate_respected``, failed the same
  way by 0.12.2 and by the 1.0 candidate: "cancel the influence job I have
  running" — no tool called, and the analyst asked which job.  A
  reference the catalogue can resolve is not a question for the human;
  the turn spent asking is a turn spent, and the human's answer is a
  string the agent could have read.  Only what no tool can tell you is
  a question.
* *"When the lookup finds more than one candidate for an act that changes
  state … never pick one silently."*  The same suite's ``label_set_choice``,
  failed the same way by both: "run influence quantification on the
  taiwan corpus" — the corpus carries two label sets, the model read the
  catalogue, saw both, submitted against one and named the second
  nowhere.  A read that finds ambiguity and an act that resolves it
  silently is a decision the human never got to see; the fix is not to
  refuse the act but to put the candidates and the choice on the page,
  where a question or a reason can be read.
* *"Before a multi-step change, read every part you will change; the plan
  goes in the answer."*  §3, "plans over prompts", and the eval suite's
  ``a_listing_is_not_a_plan`` regression (``EVAL.md`` §8.1).  The second
  half is there because the first half, alone, **contradicts the
  protocol**: every reply is one JSON object or one function call, so a
  model told to "state a plan" writes prose in the middle of a run,
  spends a turn on a malformed reply and learns nothing.  The coding pack
  found that on its own plane and said so — "a plan written as prose in
  the middle of a run is a malformed reply and costs you a turn" — and
  saying it here is what lets that pack keep only the coding-shaped part.
  The plan is therefore *what you read first*, which is on the record,
  and *what the answer states*, which is where prose is legal.
* *"Never say a test, a fetch or a computation passed without the tool
  result that shows it."*  The analyst pack's "saying 'I computed' when no
  program ran this mission is a claim about your own work that no output
  can support", and ``ROADMAP.md`` §3's "determinism over vibes".
* *"When the objective cannot be met, answer with what you have and name
  what is missing: a caveat beats a refusal."*  ``EVAL.md`` §8.2, which
  is a whole regression case, and the ``answered_with_caveat`` outcome
  that exists because of it.

**What it retires.**  Three shipped manifests and a fixture were writing
this text out by hand, and each keeps only what is particular to its own
plane:

* **analyst** drops "never state a figure the code did not print", the
  "an answer with a caveat is worth more than a refusal" half of its
  parse-failure clause, "do not describe a capability you do not have",
  and the "a number that only exists in the answer is a fabrication"
  sentence of its ``evidence_requirements``.  It keeps *a figure is
  printed by the computation that produced it* — which is the code
  plane's own failure mode and no framework's business — naming the
  table, proving a missing file with a listing, the sandbox's own facts,
  and do not overwrite an input.
* **research** drops "if a page could not be read, say so … never fill
  the gap from memory", "never invent a source", the whole "a 404 is an
  answer / do not fetch the same URL twice" clause, the do-not-retry half
  of ``host_not_allowed`` and the do-not-ask-for-a-bigger-cut half of its
  long-page section.  It keeps the citation format, the unit rule ("do
  not convert, round or combine"), *there is no computation plane here*,
  the page budget, "a search provider that refuses is a search engine
  that did not run", and "a page is a claim about a moment".
* **coding** drops "plan before you patch" (framework), "a change that
  has not been verified is a proposal, not a result" (framework), "do not
  re-send the same patch" (framework), and the never-say-the-tests-pass
  sentence of its ``evidence_requirements``.  It keeps the coding-shaped
  half of each: *your plan is the files you read* — because a plan
  written as prose mid-run is a malformed reply on this protocol — run
  ``verify test`` after patching, do not change the test to match the
  code, and the repository root.
* ``tests/fixtures/eval/stub_skill.md`` loses its ``policy:`` block
  entirely — all three lines were this module's sentences — and its
  caveat closer.  It is the honest test of this change, because the
  in-repo suite scores that fixture and every verdict has to come back
  what it was.

**Style.**  Plain, short, imperative; no ``CRITICAL``, no shouted ``MUST``,
no threats.  These are current models and the shouting registers as noise
they learn to skip; ``tests/test_prompts.py`` holds the file to it.  It is
also **byte-stable across a run and across runs** — no clock, no run id,
no count — because it is stacked into the cached prefix of every single
step: see :meth:`core.runtime.run.Run.seed` for what that prefix is worth.
"""

__all__ = ["GOVERNED_PLANE"]


#: The conduct every run is given, between the catalogue and core memory
#: — after the list of tools it governs, for recency: the reference
#: deployment measured a small model following mid-prompt conduct roughly
#: half the time.
#:
#: Eight paragraphs, 344 words, and each one earns its tokens: this is
#: re-sent on every step of every mission, so a sentence that only sounds
#: good is a sentence the deployment pays for several hundred times.
#:
#: Suppressed per-run with ``Personality(conduct="")`` — for the platform
#: that has its own conduct text and wants it in the persona instead — and
#: replaced with ``Personality(conduct="…")``.  ``None``, the default, is
#: this string.
GOVERNED_PLANE = """\
Working the plane:

This plane is closed and governed: the catalogue is all there is, and \
what it does not list you cannot do. A refusal names its scope and what \
would unblock it: read it, and never send the same call twice unchanged.

Results arrive bounded; the whole of each is in this run's store. Read on \
by handle, field or section rather than asking for a bigger cut.

A failed call is an answer: a 404, a missing file, an empty listing. Say \
which, and do not invent what it would have said. But an error whose text \
names the fix is an instruction: apply the fix and call again, once — \
changed, not repeated. And what failed this turn is not what the plane \
lacks: a capability is absent only when the catalogue or a refusal says \
so, never because an attempt at it errored.

If a number is not in the view, it is not in the draft. Every identifier \
and figure you write is one a tool returned in this run, spelled as the \
tool spelled it. A figure you derive — a sum, a share, a difference — is \
one a computation tool printed, when the plane has one; otherwise show the \
arithmetic from the returned figures.

When the request points at something the plane can list — the newest run, \
the job that is running — look it up before you ask; ask only for what no \
tool can tell you. When the lookup finds more than one candidate for an \
act that changes state — a submit, a cancel, a write — name them all in \
the answer, and either ask or say which you chose and why; never pick one \
silently.

Before a multi-step change, read every part you will change; the plan \
goes in the answer.

Never say a test, a fetch or a computation passed without the tool result \
that shows it.

When the objective cannot be met, answer with what you have and name what \
is missing: a caveat beats a refusal.
"""
