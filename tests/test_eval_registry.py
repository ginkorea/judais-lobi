# tests/test_eval_registry.py — the profile store, and the discipline in it

"""`python -m core.eval registry`, driven against real report shapes.

Three of the fixtures here are not hand-written JSON.  The extraction one
is a **copy of the report this repository ships** in `evidence/` with the
attempt list trimmed — the `meta` block, the `headline` and every `rates`
entry are the real bytes — so a change to the shape `extraction --report`
writes breaks ingestion here rather than in six months on somebody else's
report.  The ablation and measure ones are built by asking
`core.eval.ablation.Ablation` and `core.eval.measure.Matrix` for their own
`as_dict()`, which is the same guarantee by a shorter road.

The assertions that matter are the refusals and the two rules the module
exists for: **no interval below the sample floor**, and **no averaging
across interpreters**.  Both are written so that relaxing them turns a
test red — a registry that quietly merged a scorer-2 row into a scorer-3
one would look exactly like a working registry.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from core.eval import extraction as extraction_mod
from core.eval import registry as mod
from core.eval.ablation import Ablation, Arm, ArmResult
from core.eval.measure import Configured, Matrix
from core.eval.registry import (DEFAULT_REGISTRY, FLOOR_N, SCHEMA, Figure,
                                Registry, Unregisterable, deltas,
                                endpoint_kind, read_report, render, staleness)
from core.eval.run import main as eval_main
from core.eval.score import Half, Report, Totals, Verdict

FIXTURE = (Path(__file__).parent / "fixtures" / "eval" / "registry" /
           "extraction-report.json")
EVIDENCE = Path(__file__).parent.parent / "evidence"


# ── building the other two report shapes from their own producers ────────────

def _report(passed: int, missions: int, half: str = "test") -> Report:
    verdicts = tuple(
        Verdict(key=f"m{i}", flag="f", split=half, passed=i < passed)
        for i in range(missions))
    totals = Totals(missions=missions, scored=missions, passed=passed,
                    graded=missions)
    return Report(suite="s", halves={half: Half(split=half, verdicts=verdicts,
                                                overall=totals, by_flag={})})


def _meta(**over) -> dict:
    base = {"commit": "abc123def456", "date": "2026-09-10", "provider": "local",
            "model": "openai/gpt-oss-20b",
            "endpoint": "http://127.0.0.1:8011/v1", "repeat": 1,
            "per_mission_seconds": 600.0, "python": "3.10.14"}
    base.update(over)
    return base


def ablation_payload(**over) -> dict:
    """A real `Ablation.as_dict()`, one arm, one half."""
    result = ArmResult(arm=Arm(name="shadow", why="w", flags=("--cognition",)),
                       reports=(_report(18, 24),))
    return Ablation(suite="benchmark", split="test", arms=(result,),
                    meta=_meta(**over),
                    keys={"test": tuple(f"m{i}" for i in range(24))}).as_dict()


def measure_payload(**over) -> dict:
    """A real `Matrix.as_dict()`, one configuration, one half."""
    configured = Configured(name="native", reports=(_report(21, 30),))
    return Matrix(suite="stub", split="test", configured=(configured,),
                  meta=_meta(**over)).as_dict()


def write(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# ── ingestion from the real extraction shape ─────────────────────────────────

def test_the_shipped_extraction_shape_ingests_with_its_identity_intact():
    entry = read_report(FIXTURE)

    assert entry.source == "extraction"
    assert entry.identity == ("local", "openai/gpt-oss-20b")
    # The identity sentence's fields, verbatim off the report.
    assert entry.temperature == 0.2
    assert entry.constrained is False
    assert entry.prompt == "2c78315dfca7"
    assert entry.scorer == 2
    assert entry.commit == "9148adecc9fe629e9296ad84d17f72018a674270"
    assert entry.date == "2026-09-13"
    # The report names its own headline; the registry does not re-decide.
    assert entry.headline == "probe_reliable"
    assert entry.report == "extraction-report.json"


def test_every_rate_in_the_report_becomes_a_figure_with_its_k_and_n():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    entry = read_report(FIXTURE)

    # Every one, mechanically: a rate added to `rates_of` lands here with no
    # edit to the registry, which is the opposite of a maintained list.
    assert ([f.name for f in entry.figures] ==
            [r["name"] for r in payload["rates"].values()])
    figures = {f.name: f for f in entry.figures}
    assert (figures["probe_reliable"].k, figures["probe_reliable"].n) == (45, 49)
    assert (figures["grounded"].k, figures["grounded"].n) == (126, 126)
    # Never a bare rate: the sentence travels with the pair.
    assert "PROBES whose every attempt" in figures["probe_reliable"].what


def test_the_ablation_and_measure_shapes_ingest_their_run_level_pairs(tmp_path):
    ablation = read_report(write(tmp_path, "a.json", ablation_payload()))
    assert ablation.source == "ablation"
    assert [(f.name, f.k, f.n) for f in ablation.figures] == [
        ("shadow/test", 18, 24)]
    assert "--cognition" in ablation.figures[0].what

    matrix = read_report(write(tmp_path, "m.json", measure_payload()))
    assert matrix.source == "measure"
    assert [(f.name, f.k, f.n) for f in matrix.figures] == [("native/test",
                                                             21, 30)]
    # Neither header states a temperature, and none is invented for it.
    assert ablation.temperature is None and matrix.temperature is None


def test_a_skipped_arm_contributes_no_figures_at_all(tmp_path):
    payload = ablation_payload()
    payload["arms"].append({"name": "graph", "why": "", "flag_delta": ["--g"],
                            "skipped": "the CLI does not accept --g",
                            "command": [], "directories": [],
                            "missions": {}, "runs": {"test": [0, 0]},
                            "interval": {}, "infra": {}, "paired": {},
                            "reports": []})
    entry = read_report(write(tmp_path, "a.json", payload))
    assert [f.name for f in entry.figures] == ["shadow/test"]


# ── the three refusals ───────────────────────────────────────────────────────

@pytest.mark.parametrize("missing", ["provider", "model"])
def test_a_report_without_its_model_identity_is_refused(tmp_path, missing):
    payload = ablation_payload(**{missing: ""})
    with pytest.raises(Unregisterable) as caught:
        read_report(write(tmp_path, "a.json", payload))
    assert missing in str(caught.value)
    assert "identity" in str(caught.value)


def test_a_shape_no_subcommand_writes_is_refused_by_name(tmp_path):
    # The head-to-head summary in `evidence/` is exactly this case: a real
    # artifact, a real comparison, and no model anywhere in it.
    path = write(tmp_path, "summary.json", {"winner": "v1.2.0",
                                            "aggregate": {"v1.2.0": {}}})
    with pytest.raises(Unregisterable) as caught:
        read_report(path)
    assert "meta" in str(caught.value)

    path = write(tmp_path, "odd.json", {"meta": _meta(), "something": [1]})
    with pytest.raises(Unregisterable) as caught:
        read_report(path)
    for kind, _ in mod.SHAPES:
        assert kind in str(caught.value)


def test_the_head_to_head_summary_this_repo_ships_is_refused_not_guessed_at():
    summary = EVIDENCE / "head-to-head" / "head-to-head-2026-09-14-summary.json"
    if not summary.exists():                      # evidence is not a fixture
        pytest.skip("evidence/head-to-head is not in this tree")
    with pytest.raises(Unregisterable):
        read_report(summary)


def test_re_adding_the_same_bytes_is_a_no_op_that_says_so(tmp_path):
    registry = Registry()
    first, added = registry.add(FIXTURE)
    assert added is True
    copy = tmp_path / "renamed.json"
    copy.write_bytes(FIXTURE.read_bytes())
    again, added = registry.add(copy)
    assert added is False                    # a different NAME, the same bytes
    assert again is first
    assert len(registry.entries) == 1


def test_a_report_with_nothing_counted_is_refused(tmp_path):
    payload = ablation_payload()
    payload["arms"][0]["runs"] = {"test": [0, 0]}
    with pytest.raises(Unregisterable) as caught:
        read_report(write(tmp_path, "a.json", payload))
    assert "nothing to register" in str(caught.value)


def test_a_file_that_is_not_json_is_refused_with_the_path(tmp_path):
    path = tmp_path / "x.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(Unregisterable) as caught:
        read_report(path)
    assert "not JSON" in str(caught.value)


# ── the endpoint scrub ───────────────────────────────────────────────────────

@pytest.mark.parametrize("url,expected", [
    ("http://127.0.0.1:8011/v1", "http://loopback"),
    ("http://localhost:8770", "http://loopback"),
    ("https://10.4.1.9:8000/v1", "https://private"),
    ("https://box.internal/v1", "https://private"),
    ("https://api.example.com/v1?key=sk-secret", "https://public"),
    ("https://token@api.example.com/v1", "https://public"),
    ("", ""),
    # Nothing the input said survives, even where the input looks like a
    # scheme: `host:8011/v1` parses with `host` AS the scheme.
    ("pool.someone-else.net:8011/v1", "public"),
    ("ftp://files.example.com", "other://public"),
    ("https://[not-closed", "unparsed"),
    ("http://", "http://unstated"),
])
def test_the_endpoint_is_reduced_to_scheme_and_a_host_class(url, expected):
    assert endpoint_kind(url) == expected


def test_every_word_of_the_scrub_comes_from_a_closed_set():
    vocabulary = {"", "unparsed", "unstated", "loopback", "private", "public"}
    for url in ("weird-scheme://box.corp:9/v1", "pool.someone-else.net:8011",
                "http://10.1.2.3", "nonsense", "https://[x", ""):
        got = endpoint_kind(url)
        scheme, _, klass = got.rpartition("://")
        assert klass in vocabulary, got
        assert scheme in (mod.SCHEMES | {"other", ""}), got


def test_no_host_port_or_credential_survives_the_scrub():
    scrubbed = endpoint_kind("https://sk-live-abcd@pool.someone-else.net:8443"
                             "/v1?key=sk-2")
    for leak in ("someone-else", "8443", "sk-live-abcd", "sk-2", "/v1"):
        assert leak not in scrubbed
    assert scrubbed == "https://public"


# ── the sample floor ─────────────────────────────────────────────────────────

def test_below_the_floor_a_figure_gets_the_mark_and_no_interval():
    small = Figure(name="conflict_surfaced", k=6, n=6)
    assert small.sufficient is False
    assert small.interval == ()
    assert "insufficient sample" in small.text
    assert f"n<{FLOOR_N}" in small.text


def test_at_the_floor_the_interval_comes_back():
    at = Figure(name="trap", k=FLOOR_N, n=FLOOR_N)
    assert at.sufficient is True
    assert at.interval == extraction_mod.wilson(FLOOR_N, FLOOR_N)
    assert "insufficient" not in at.text
    # One below is the other side of the same line.
    assert Figure(name="trap", k=FLOOR_N - 1, n=FLOOR_N - 1).interval == ()


def test_the_rendered_table_marks_the_small_rows_and_never_bands_them():
    registry = Registry()
    registry.add(FIXTURE)
    text = render(registry, today=date(2026, 9, 13))
    # `conflict_surfaced` is 6/6 in the shipped report.
    line = next(l for l in text.splitlines() if "`conflict_surfaced`" in l)
    assert "insufficient sample" in line
    assert "%–" not in line                         # no interval on that row
    # `probe_reliable` is 45/49 and gets one.
    line = next(l for l in text.splitlines() if "probe_reliable" in l)
    assert "%–" in line


# ── no aggregation across interpreters ───────────────────────────────────────

def _two_interpreters(tmp_path) -> Registry:
    """The same model, the same figure, two scorers."""
    registry = Registry()
    registry.add(write(tmp_path, "one.json",
                       ablation_payload(date="2026-09-10")))
    second = ablation_payload(date="2026-09-11")
    second["meta"]["scorer"] = 3
    second["arms"][0]["runs"]["test"] = [24, 24]
    registry.add(write(tmp_path, "two.json", second))
    return registry


def test_two_interpreters_are_two_rows_and_are_never_averaged(tmp_path):
    registry = _two_interpreters(tmp_path)
    entries = registry.entries
    assert len(entries) == 2
    assert entries[0].interpreter != entries[1].interpreter

    text = render(registry, today=date(2026, 9, 13))
    rows = [l for l in text.splitlines() if "`shadow/test`" in l]
    assert len(rows) == 2, "two interpreters must stay two rows"
    assert any("18/24" in row for row in rows)
    assert any("24/24" in row for row in rows)
    # The merged pair is the number this rule exists to prevent.
    assert "42/48" not in text


def test_a_paired_delta_is_only_drawn_inside_one_interpreter(tmp_path):
    # Two scorers: no pair, so no delta at all.
    assert deltas(_two_interpreters(tmp_path).entries) == []

    # Same interpreter twice: exactly one delta, and it is the newest pair.
    registry = Registry()
    registry.add(write(tmp_path, "a.json", ablation_payload(date="2026-09-10")))
    later = ablation_payload(date="2026-09-12")
    later["arms"][0]["runs"]["test"] = [24, 24]
    registry.add(write(tmp_path, "b.json", later))
    found = deltas(registry.entries)
    assert len(found) == 1
    assert found[0].figure == "shadow/test"
    assert found[0].points == pytest.approx(0.25)
    assert "18/24 → 24/24" in found[0].text


def test_a_delta_is_withheld_when_either_side_is_under_the_floor(tmp_path):
    registry = Registry()
    for day, pair in (("2026-09-10", [4, 6]), ("2026-09-12", [6, 6])):
        payload = ablation_payload(date=day)
        payload["arms"][0]["runs"]["test"] = pair
        registry.add(write(tmp_path, f"{day}.json", payload))
    (delta,) = deltas(registry.entries)
    assert delta.points is None
    assert "withheld" in delta.text
    assert f"n={FLOOR_N}" in delta.text


# ── one owner for the arithmetic ─────────────────────────────────────────────

def test_the_registry_uses_the_packages_one_wilson_and_owns_no_twin():
    assert mod.wilson is extraction_mod.wilson
    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "def wilson" not in source, "a local twin is the thing to avoid"
    assert "math.sqrt" not in source
    # And the number it prints is that function's, not a rounding of it.
    figure = Figure(name="x", k=45, n=49)
    assert figure.interval == extraction_mod.wilson(45, 49)


# ── the store on disk ────────────────────────────────────────────────────────

def test_the_file_is_a_pure_function_of_the_reports_it_holds(tmp_path):
    one = write(tmp_path, "one.json", ablation_payload(date="2026-09-10"))
    two = write(tmp_path, "two.json", measure_payload(date="2026-09-11"))

    forward, backward = Registry(), Registry()
    forward.add(one)
    forward.add(two)
    backward.add(two)
    backward.add(one)
    # Same reports, opposite order, same bytes — and no timestamp in them.
    assert forward.to_json() == backward.to_json()
    row = json.loads(forward.to_json())["models"][0]["measurements"][0]
    # Only the REPORT's date; no ingestion time anywhere, for the reason
    # `core.eval.score.Report` carries none.
    assert row["date"] == "2026-09-10"
    assert not [key for key in row if key in ("added", "ingested", "at")]


def test_a_round_trip_through_the_file_keeps_every_figure(tmp_path):
    path = tmp_path / "registry.json"
    first = Registry()
    first.add(FIXTURE)
    first.save(path)
    again = Registry.load(path)
    assert again.to_json() == first.to_json()
    assert [(f.name, f.k, f.n) for f in again.entries[0].figures] == [
        (f.name, f.k, f.n) for f in first.entries[0].figures]


def test_an_absent_registry_loads_empty_and_a_wrong_schema_is_refused(tmp_path):
    assert Registry.load(tmp_path / "nope.json").entries == ()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": SCHEMA + 1, "models": []}),
                   encoding="utf-8")
    with pytest.raises(Unregisterable) as caught:
        Registry.load(bad)
    assert "schema" in str(caught.value)


def test_rm_takes_a_prefix_and_refuses_what_it_cannot_resolve(tmp_path):
    registry = Registry()
    entry, _ = registry.add(FIXTURE)
    with pytest.raises(Unregisterable):
        registry.remove("ffffff")
    removed = registry.remove(entry.digest[:8])
    assert removed.digest == entry.digest
    assert registry.entries == ()
    with pytest.raises(Unregisterable):
        registry.remove("")


# ── staleness ────────────────────────────────────────────────────────────────

def test_the_age_of_the_newest_measurement_is_stated_and_marked_when_old():
    fresh = staleness("2026-09-10", today=date(2026, 9, 13))
    assert "3 day(s) old" in fresh and "stale" not in fresh
    old = staleness("2026-01-01", today=date(2026, 9, 13))
    assert "stale" in old
    assert "no measurement carries a date" in staleness("")


# ── the subcommand, end to end ───────────────────────────────────────────────

def test_add_show_and_rm_through_the_cli(tmp_path, capsys):
    store = tmp_path / "registry.json"

    assert eval_main(["registry", "--registry", str(store), "add",
                      str(FIXTURE)]) == 0
    assert "registered extraction report" in capsys.readouterr().out
    assert store.exists()

    # Twice is quiet and writes nothing new.
    before = store.read_bytes()
    assert eval_main(["registry", "--registry", str(store), "add",
                      str(FIXTURE)]) == 0
    assert "already registered" in capsys.readouterr().out
    assert store.read_bytes() == before

    assert eval_main(["registry", "--registry", str(store), "show"]) == 0
    shown = capsys.readouterr().out
    assert "openai/gpt-oss-20b" in shown
    assert "does not route" in shown                # the scope statement
    assert "45/49" in shown

    assert eval_main(["registry", "--registry", str(store), "show",
                      "--model", "openai/gpt-oss-20b"]) == 0
    assert "openai/gpt-oss-20b" in capsys.readouterr().out
    assert eval_main(["registry", "--registry", str(store), "show",
                      "--model", "nothing-here"]) == 1
    assert "no model" in capsys.readouterr().err

    digest = json.loads(store.read_text(encoding="utf-8"))[
        "models"][0]["measurements"][0]["digest"]
    assert eval_main(["registry", "--registry", str(store), "rm",
                      digest[:12]]) == 0
    assert "removed" in capsys.readouterr().out
    assert Registry.load(store).entries == ()


def test_the_cli_refuses_a_bad_report_with_exit_one(tmp_path, capsys):
    path = write(tmp_path, "bad.json", {"meta": _meta(model=""),
                                        "arms": [{"name": "a", "runs":
                                                  {"test": [1, 2]}}]})
    assert eval_main(["registry", "--registry", str(tmp_path / "r.json"),
                      "add", str(path)]) == 1
    assert "model" in capsys.readouterr().err
    assert not (tmp_path / "r.json").exists()


def test_an_empty_registry_renders_something_a_reader_can_act_on(tmp_path,
                                                                 capsys):
    assert eval_main(["registry", "--registry", str(tmp_path / "r.json"),
                      "show"]) == 0
    out = capsys.readouterr().out
    assert "Nothing registered" in out
    assert "registry add" in out


def test_show_json_prints_the_store_itself(tmp_path, capsys):
    store = tmp_path / "registry.json"
    eval_main(["registry", "--registry", str(store), "add", str(FIXTURE)])
    capsys.readouterr()
    assert eval_main(["registry", "--registry", str(store), "show",
                      "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == SCHEMA
    assert payload["models"][0]["model"] == "openai/gpt-oss-20b"


# ── the seeded registry this repository commits ──────────────────────────────

def test_the_committed_registry_is_exactly_what_add_produces(tmp_path):
    """The worked example stays reproducible, or this goes red.

    A store nobody can regenerate from the reports beside it is a store
    somebody edited by hand, which is the one thing the door exists to
    prevent.  So: every row of `evidence/registry.json` is re-ingested from
    the report of that name under `evidence/`, and has to come out the same.
    """
    store = EVIDENCE / "registry.json"
    if not store.exists():
        pytest.skip("evidence/registry.json is not in this tree")
    committed = Registry.load(store)
    assert committed.entries, "the worked example is empty"
    rebuilt = Registry()
    for entry in committed.entries:
        found = [p for p in EVIDENCE.rglob(entry.report) if p.is_file()]
        assert found, f"{entry.report} is registered but not in evidence/"
        rebuilt.add(found[0])
    assert rebuilt.to_json() == committed.to_json()


def test_the_default_path_is_a_convention_and_not_a_search():
    # Relative, so `--registry` is the only way to name another one; an
    # ancestor walk is the 1.1.1 locator bug this deliberately does not have.
    assert not DEFAULT_REGISTRY.is_absolute()
    assert str(DEFAULT_REGISTRY) == "evidence/registry.json"
    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert ".parents[" not in source and "rglob" not in source
