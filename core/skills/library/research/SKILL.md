---
name: research
description: >
  Read pages on the open web and answer from them, citing the URL for every
  claim. Reads only: nothing here writes to a site, runs code, or reaches
  anything but HTTP(S) GET.
skill:
  skill_id: research
  version: 1.0.0
  when_to_use: >
    A question whose answer is on the web and not in the model: what a page
    says, what two pages disagree about, what a figure is in a source
    somebody can check. Also the right skill when the honest answer is that
    the page could not be read.
  inputs:
    question: string
    urls: "list of strings?"
    max_pages: "integer?"
  allowed_tools:
    - fetch_page_content
    - perform_web_research
    - perform_web_search?
    - fs?
  sandbox: none
  retrieval_strategy: >
    Start from the URLs you were given. If you were given none and search is
    available, search first and then read the pages you chose from the
    results; a snippet is not a source. One page at a time with
    fetch_page_content when you know which page you want; perform_web_research
    with a list of urls when you want several at once and one call is cheaper
    than four. Follow a link only when the page you read says the answer is
    on the other side of it, and say which link you followed.
  ranking: >
    Prefer the page that states the figure over the page that repeats it.
    Prefer the source a reader can check over the one behind a login. Where
    two pages disagree, report both and say they disagree; do not pick a
    winner the sources do not support.
  policy:
    - Cite the URL for every claim. A claim with no URL beside it is not an
      answer this skill gives.
    - Quote figures exactly as the page states them, with the unit the page
      used. Do not convert, round or combine.
    - Do not state a figure you calculated. If a comparison needs arithmetic,
      give the two figures the pages state and say what the difference is
      derived from.
    - If a page could not be read, say so and say WHICH page and why -
      the status, the refusal, the timeout. Never fill the gap from memory.
    - Never invent a source. A URL you did not fetch is not a citation, and a
      plausible URL is the worst kind of invention because it looks checkable.
    - Read no more than the pages the question needs. If you decide more are
      needed, say why before you read them.
    - A search provider that refuses is a search engine that did not run. It
      is not evidence that the web holds nothing.
    - A page is a claim about a moment. Say when you read it if the answer
      could change.
    - A 404 is an answer. Do not fetch the same URL twice, and do not go
      searching for a page that has already told you it is not there -
      report it and move on to what you can read.
  evidence_requirements: >
    Every figure and every named source in the answer must appear in
    something a tool returned in this run. A long page comes back bounded in
    the transcript and whole in the mission result store: read the section
    you need with mission_result(handle="rN", path="sections[i].text")
    rather than fetching the page again or answering from the part you can
    still see.
  output_format: >
    Findings first, as prose or a short list, with a bracketed source marker
    like [S1] after each claim. Then a Sources section: one line per marker,
    the marker and the full URL, in the order they were first cited. Then, if
    anything could not be read, a line saying what and why. Use [S1], [S2]
    for the markers and never a bare number in brackets - a bare number reads
    as a figure and is checked as one.
  grounding:
    identifier_pattern: '((?:https?://[^\s<>()\[\]{}",;]+[^\s<>()\[\]{}",;.:])|(?:\bdoc\.[a-z0-9-]+\b))'
    number_pattern: '(?<![\w.])[+-]?\d(?:[\d,_]*\d)?(?:\.\d+)?(?![\w])'
    ignore:
      - "400"
      - "401"
      - "403"
      - "404"
      - "408"
      - "410"
      - "429"
      - "500"
      - "502"
      - "503"
      - "504"
    must_cite:
      identifiers: 1
---

# Research

You read the web and you say where everything came from.

## The one rule

**A claim and its URL travel together.** Not at the bottom of the answer, not
"according to the documentation" — the marker goes on the sentence and the
marker resolves to a full URL in the Sources list. The reason is not
tidiness: an answer whose sources cannot be checked is indistinguishable from
an answer the model wrote out of its own memory of the internet, and the
second one is wrong in ways nobody can see.

## What you can and cannot do here

You can fetch an `http` or `https` URL and read what it says. You get the
page's title, its sections in document order, and the links on it. You can
read several pages in one call. You can search **only if a provider is
configured**, and if it is not, the tool will say so by name — that is the
search engine failing, not the web being empty, and the difference matters
enough to state in the answer.

You cannot run JavaScript, log in, submit a form, or read anything that is
not text. You cannot read a page on a host the operator excluded. You do not
write to any site. If the operator gave you a filesystem tool you may save a
report locally when asked to; that is the only writing in this skill.

## A long page

Pages are bigger than transcripts. What you see of a large page is a bounded
cut with the middle removed and a marker saying so. **The whole page is still
there**, in the mission result store, under the handle the marker names.

    mission_result(handle="r2")                        # what is stored
    mission_result(handle="r2", path="sections[41].text")
    mission_result(handle="r2", path="title")
    mission_result(handle="r2", path="links[3].url")

Section numbers are positions in the stored page, in document order. Walk to
the one you want — the headings are in `headings` and in each section's
`heading` field — and read that. Do not ask for a bigger cut, do not fetch
the page again hoping for a different slice, and above all do not answer from
the half you can see while a figure sits in the half you cannot.

## When a page is not there

A 404, a timeout, a host outside the allow-list and a PDF are four different
answers and the mission is better for all four being said out loud:

* **404 / 410** — the page is not there. Say the URL and the status.
  (HTTP status codes are on the grounding block's `ignore` list,
  because a status is a protocol word and not a figure about the
  world. Every other number in your answer is checked.)
* **timeout / unreachable** — you did not read it. It may exist.
* **`host_not_allowed`** — the operator excluded that host for this run.
  That is a decision, not a fault: do not retry it, do not look for another
  route to the same content, and say plainly that you were not permitted to
  read it.
* **`not_text` / `too_large`** — there is something at that URL and it is not
  something you can read.

An answer that says "I could not read two of the three, here is what the
third says" is worth more than one that quietly answers from one source, and
far more than one that fills the gap.

## What a good answer looks like

    The array generated 1482 MWh in 2025 [S1], and the farm 2940 MWh [S2].
    The longest single outage of the year was 37 hours, on turbine T-04
    [S3]; the wind report does not carry that figure and points at the
    maintenance log for it.

    Sources:
    [S1] https://example.org/archive/solar-array.html
    [S2] https://example.org/archive/wind-farm.html
    [S3] https://example.org/archive/turbine-log.html

    Not read: https://example.org/archive/retired.html — HTTP 404.

Every figure in that answer is on the page its marker names, in the unit the
page used, and every URL was fetched in this run. That is the whole standard.
