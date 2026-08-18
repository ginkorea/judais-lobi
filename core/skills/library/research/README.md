# The `research` mission pack

Read pages on the open web and answer from them, with a URL beside every
claim. Ships with the framework; needs no API key, no browser and no
search engine to do the thing it is for.

```
SKILL.md        what the model is told and held to
missions.yaml   the eval suite: twelve missions over the fixture site below
fixtures/       a small archive of HTML pages — the plane the suite is graded on
README.md       this file
```

---

## What it does

Given a URL, it reads the page and cites it. Given several, it reads them
into one pack. Given a page that links to another, it can follow the link.
Given a page it cannot read, it says which page and why, and does not fill
the gap from memory.

Three tools, all reads:

| tool | what it is for |
|---|---|
| `fetch_page_content` | one URL → a typed page: `url`, `final_url`, `status`, `title`, `fetched_at`, `sections[]` (heading + text, in document order), `links[]` |
| `perform_web_research` | several URLs (or a query, or `mode=academic`) → one pack of typed pages, plus `failed[]` with the reason each unread URL was not read |
| `perform_web_search?` | ranked results **if a provider is configured**. Optional in the closed set, because research without a search engine is still research |

`fs` is in the closed set as optional too, so a mission asked to save its
report can. Nothing here writes to a website, runs code, or reaches
anything but HTTP(S) GET.

## The profile

```
judais --mission --skill research --profile research "…"
```

`research` is a capability profile — `dev` plus `http.read`, and nothing
else. It exists because these tools used to need `--profile ops`, which
also grants `git push`, `pip install` and `fs.delete`: an agent asked to
read three public pages was handed a deploy right, and
`mission_started.profile: "ops"` said something about that run that was not
true. `--profile research` reads honestly: **read the web, write nothing,
run nothing beyond dev.** `JUDAIS_LOBI_PROFILE=research` is the environment
form. Under `safe` or `dev` these tools are denied and the refusal names
`--profile research` as the fix.

## Configuration

Everything below is optional. With none of it set, `fetch_page_content` and
`perform_web_research(urls=[…])` work.

| variable | meaning |
|---|---|
| `RESEARCH_ALLOWED_HOSTS` | comma-separated hosts this process may fetch. **Unset means no restriction.** A leading dot covers subdomains (`.example.org`). A host outside it is refused by name before a socket is opened — the refusal says it is an operator's decision and not to retry |
| `RESEARCH_MAX_PAGE_BYTES` | how much of a response body is read before the fetch is refused as `too_large`. Default 4 MiB |
| `RESEARCH_TIMEOUT_S` | seconds before a fetch gives up. Default 20 |
| `SEARCH_PROVIDER` | which search backend answers `perform_web_search`: `duckduckgo` (default, keyless, a scrape of an endpoint nobody promised), `searxng`, or one a platform registered |
| `SEARXNG_URL` | the SearXNG instance for `SEARCH_PROVIDER=searxng`. No default: a default would be somebody else's bandwidth |

**A keyed provider is twenty lines in your own repository**, and none ships
here — a framework that hard-coded one vendor's endpoint would have an
opinion about whose search you buy:

```python
from core.tools.web_search import register_provider, SearchUnavailable

def brave(query, max_results, timeout):
    ...                      # returns [{"title", "url", "snippet"}, …]
    raise SearchUnavailable("brave: no key in BRAVE_API_KEY")

register_provider("brave", brave)     # then run with SEARCH_PROVIDER=brave
```

A provider that cannot answer must raise `SearchUnavailable`. Returning `[]`
means *the index holds nothing for this query*, which is a finding a mission
may report. The two are never conflated, and the old tool's `"No results
found."` — which meant both — is the failure that put providers here.

## Long pages

A page is bigger than a transcript. What the model sees is
`core.bounding.bound_result`'s head-and-tail cut with a marker naming the
store handle; the **whole** extraction stays in `core.runtime.results`. The
skill teaches the model to walk into it rather than ask for more:

```
mission_result(handle="r2")                          # what is stored
mission_result(handle="r2", path="sections[41].text")
mission_result(handle="r2", path="headings")
```

`fixtures/capacity.html` exists to make that testable: 400 sections,
138 kB rendered, and the figure a mission asks for sits in the middle —
the part the bounded cut removes.

## The fixture site

`fixtures/` is a small invented archive (the "Meridian Field Station",
which is not a real place) with a headline figure per page, one page that
links to the page holding a figure it does not state, one deliberately
enormous page, one glossary that makes a question genuinely ambiguous, and
one index entry pointing at a page that is **not there** — the 404 is a
mission.

Serve it by hand:

```
python -m http.server 8080 --bind 127.0.0.1 \
    --directory core/skills/library/research/fixtures
judais --mission --skill research --profile research \
    "What did the solar array generate in 2025? The archive index is at
     http://127.0.0.1:8080/index.html"
```

The tests serve a **staged copy** of the same directory on an
ephemeral port (`tests/research_fixture_server.py` through
`Pack.stage_fixtures`, never out of the installed pack), which is why nothing
in the suite asserts a whole URL — only a path.

## The suite

`missions.yaml` is a `core.eval` suite: twelve missions, one per capability
flag (two on `chaining`), four held out.

```python
import core.skills
suite = core.skills.load("research").suite()     # loaded, and checked
```

```bash
python -m core.eval live --suite core/skills/library/research/missions.yaml \
    --out /tmp/research-runs -- judais {objective} \
    --skill research --profile research
```

Two things the suite depends on that are worth knowing before you run it:

* **the entry point is plane configuration, not part of the question.** The
  fixture site's base URL changes with the port, and a mission prompt is
  given verbatim every time — so the address is appended to the *system
  message* by whatever drives the run, exactly as `--mcp-stdio` is how the
  stub suite's plane arrives. The prompts name pages by their archive id
  (`doc.solar-array`), never by address;
* **the pack's suite is checked with the coverage scoped to the flags it
  captures** (`core.skills.library.check_pack_suite`, reached by
  `Pack.suite()`). This pack happens to capture all eleven, so
  `python -m core.eval check --suite …/missions.yaml` accepts it directly
  too — but that is a property of this suite and not something a pack has
  to arrange.

Recorded streams for every mission — a good agent and, where the mission
has one, the bad agent it exists to catch — are committed under
`tests/fixtures/pack_research/` and re-recorded with
`JUDAIS_LOBI_RESEARCH_FIXTURES=refresh`.
