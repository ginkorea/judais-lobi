> Historical (Feb 2026). For current behaviour see README.md, CONTRACT.md, PLATFORMS.md.

# Phase 8 Plan — Retrieval, Context Discipline & Local Inference

**Status: closed 15 Aug 2026 (0.9.0).** The plan below is the February
document, left as written. What actually shipped rarely used the file names it
proposed, so the table says where each milestone landed instead. Two rows are
deliberately not code in this repo: D1 became an eval question, and B3 became a
durability question. Both are named in `NEXT_STEPS.md` with the phase that owns
them next.

## Disposition

| Milestone | Where it landed |
| --- | --- |
| **A** — symbol-aware retrieval | `core/context/spans.py`, reached as the `symbol` action of the `repo_map` tool (`core/tools/descriptors.py`) and asked for by name by the RETRIEVE role (`core/kernel/roles.py`), which settles with `("repo_map", "symbol")`. Tests: `tests/test_symbol_retrieval.py`. No `symbol_lookup` tool and no `span_index.py`: an action on the tool that already owns the map beat a sixth tool. |
| **B1** — global context accounting | `core/runtime/context_window.py` — `resolve_profile` is the one cascade that answers how big the window is (backend probe → config → model default → provider default), and one estimator serves every caller. There is no `context_budget.py`; a second module would have been a second opinion. |
| **B2** — context management at every prompt build | Chat: `Agent.chat` (`core/agent.py`) routes through `ContextWindowManager`. Mission: `MissionWindow` (0.8.2), with the compaction reported on the stream as `compacted` on `step_started` rather than written to a side file. Kernel roles: 0.9.0 — the roles route through the same owner, and their compactions are recorded as a phase artifact. |
| **B3** — tool-log routing | Partial, and deferred on purpose. `core/tools/tool_output.py` writes full logs under `.judais-lobi/tool_logs` and puts a bounded summary plus a retrieval hint in context; putting those logs *beside the run's durable transcript* waits on there being one — NEXT_STEPS Phase 2 (thread primitive, `SessionManager` as its client). |
| **C** — local inference bring-up | `core/runtime/backends/local_backend.py`: OpenAI-compatible chat completions, SSE streaming, a `GET /models` probe that yields `max_model_len` as `BackendCapabilities.max_context_tokens`, and connect-refused retries. Resolution and `LOCAL_API_BASE`/`LOCAL_MODEL` in `core/runtime/provider_config.py`. |
| **C4** — offline golden tests | `tests/test_local_backend.py` against a stub server, plus `tests/mcp_stub_server.py` for the tool plane, so the whole path runs with no GPU and no network. |
| **D1** — model selection criteria | Superseded. A criteria document would have been an opinion; NEXT_STEPS Phase 3 puts an eval harness in the repo and answers the same question with a score that is reproducible from recorded runs. No `docs/model_selection.md`. |
| **D2** — config schema | `.judais-lobi.yml` carries the `context:` keys (`max_context_tokens`, `max_output_tokens`, `provider_defaults`, `model_overrides`, …) — see `ContextConfig.from_project`. The endpoint probe deliberately outranks them: `max_model_len` is measured and a config line is declared. |
| **E** — documentation | README: `--provider local` setup, the context/compaction behaviour, the `context:` block, and the retrieval tooling. This table and the ROADMAP checklist close the loop. |

Two things named in this plan were removed rather than finished, both in 0.9.0.
The baseline's `core/runtime/gpu.py` stub is gone with the VRAM cap it fed:
the client's device list never described the server's window, and the local
backend talks to a serving endpoint that is routinely another machine. And
`core/kv_prefix.py` — from Phase 3, never imported by anything but its test —
went with it.

## Goals
1. Prevent KV cache overflow by enforcing context budgets at every prompt build.
2. Improve retrieval precision (symbol‑aware, span‑based) to avoid over‑stuffing context.
3. Bring up local inference via vLLM / TRT‑LLM with GPU‑aware context sizing.
4. Keep the system operational with API backends when local inference is unavailable.

## Non‑Goals
- No GPU performance tuning (Phase 9).
- No large‑scale benchmark suite (Phase 10).
- No tool‑call streaming or tool calling via model APIs (still tool‑bus‑driven).

## Current State (Baseline)
- Context window manager exists for direct chat (`core/runtime/context_window.py`).
- Tool output rolling summaries exist (`core/tools/tool_output.py`).
- GPU profile detection stub exists (`core/runtime/gpu.py`).
- Local backend stub exists (`core/runtime/backends/local_backend.py`).

Phase 8 extends these into agentic phases and production‑ready local backend integration.

---

## Milestone A — Retrieval Discipline (Symbol‑Aware)
**Objective:** Pull only the needed function/class spans and minimize prompt size.

### A1. Symbol Span Retrieval
- Add `core/context/span_lookup.py`:
  - `extract_span(file_path, symbol_name) -> (start_line, end_line, text)`
  - For Python: AST lookup of `FunctionDef` / `ClassDef`.
  - For tree‑sitter languages: use existing extractor nodes when available.
  - Regex fallback when parser is unavailable.
- Add `core/context/span_index.py`:
  - Build a lightweight index from `RepoMapData` symbols to line spans.
  - Cache in `.judais-lobi/cache/repo_map/` alongside current cache entries.

### A2. Tooling / Access
- Add new ToolBus tool: `symbol_lookup`.
  - Inputs: `file_path`, `symbol_name` or `symbol_signature`.
  - Outputs: snippet, file_path, start/end line.
  - Scope: `repo.read` (or `fs.read`, depending on the current scope taxonomy).
- Ensure ToolBus returns structured errors for missing symbol.

### A3. Integration
- Update planner prompts to request symbols (not entire files) when possible.
- Update `RepoMap` to include symbol IDs that map to spans.

### Tests
- `tests/test_span_lookup.py`
- `tests/test_symbol_lookup_tool.py`
- Extend repo map tests to validate cached span indices.

---

## Milestone B — Context Window Enforcement (Agentic + Direct)
**Objective:** All prompt construction (direct chat + agentic phases) respects a strict context limit.

### B1. Global Context Accounting
- Introduce `core/runtime/context_budget.py`:
  - Central place to compute total token estimates for a message list.
  - Provide `ContextBudgetResult` with: total, limit, overflow, summary_used.

### B2. Phase‑Level Context Manager
- Add `ContextWindowManager` hooks to agentic prompt assembly (phases PLAN/RETRIEVE/PATCH/CRITIQUE/RUN/FIX):
  - Wherever prompts are assembled, pass message list through `ContextWindowManager`.
  - If compaction happens, write a `context_warn_<n>.json` artifact with stats.

### B3. Tool Output Routing
- For tool results inserted into history or artifacts, ensure:
  - Full logs persist to `sessions/<id>/tool_logs` (not only repo root).
  - Summaries are inserted into context.

### Tests
- `tests/test_context_budget.py`
- `tests/test_context_integration_agentic.py`

---

## Milestone C — Local Inference Bring‑Up
**Objective:** Connect the runtime to a local vLLM/TRT‑LLM server with capability probing.

### C1. Backend Implementation
- Implement `core/runtime/backends/local_backend.py` using HTTP calls:
  - vLLM OpenAI‑compatible endpoint (`/v1/chat/completions`).
  - Support streaming (SSE) if available.
  - Respect `max_tokens` for output.

### C2. Instance‑Aware Limits
- Add a `/health` or `/v1/models` probe on startup:
  - Pull model name(s) and max context if exposed.
  - Set `BackendCapabilities.max_context_tokens` accordingly.

### C3. Provider Resolution
- Extend `core/runtime/provider_config.py`:
  - Allow `ELF_PROVIDER=local`.
  - Add `LOCAL_API_BASE` and `LOCAL_MODEL` env support.

### C4. Offline Golden Tests
- Add a dry‑run test mode (mocked local backend):
  - Verify message formatting, streaming handling, and error surfaces.

### Tests
- `tests/test_local_backend.py`
- `tests/test_provider_resolution_local.py`

---

## Milestone D — Model Selection Criteria
**Objective:** Make model choice explicit and repeatable.

### D1. Criteria Document
- Add `docs/model_selection.md` with:
  - Minimum context window
  - Required tool‑call reliability
  - Coding benchmark expectations
  - Quantization compatibility

### D2. Config Schema
- Add `.judais-lobi.yml` config entries:
  - `runtime.local.model`
  - `runtime.local.api_base`
  - `runtime.local.max_context_tokens`
  - `runtime.local.max_output_tokens`

---

## Milestone E — Documentation & Roadmap Updates
- Update README with:
  - Local inference setup steps (vLLM/TRT‑LLM).
  - Context window management + auto‑compaction behavior.
  - Retrieval tool usage examples.
- Update ROADMAP Phase 8 checklist and Definition of Done.

---

## Proposed File Changes

### New
- `core/context/span_lookup.py`
- `core/context/span_index.py`
- `core/tools/symbol_lookup_tool.py`
- `core/runtime/context_budget.py`
- `docs/model_selection.md`
- `tests/test_span_lookup.py`
- `tests/test_symbol_lookup_tool.py`
- `tests/test_context_budget.py`
- `tests/test_context_integration_agentic.py`
- `tests/test_local_backend.py`
- `tests/test_provider_resolution_local.py`

### Modified
- `core/context/repo_map.py` (index + cache)
- `core/tools/descriptors.py` (new tool)
- `core/runtime/backends/local_backend.py`
- `core/runtime/provider_config.py`
- `README.md`
- `ROADMAP.md`

---

## Risk Notes
- **Token estimation accuracy:** a heuristic token estimator can be off by 20–30%. Mitigate via conservative safety margins.
- **Local backend heterogeneity:** vLLM and TRT‑LLM expose slightly different APIs. Start with OpenAI‑compatible endpoints only.
- **Symbol resolution gaps:** tree‑sitter coverage may be incomplete. Keep regex fallback and return partial spans.

---

## Definition of Done (Phase 8)
- All prompt construction flows through `ContextWindowManager` with hard limits.
- Oversized tool outputs never crash context: full logs are stored and referenced.
- Symbol‑aware retrieval tool works across Python + at least one tree‑sitter language.
- Local backend can run a full offline task on at least one GPU profile (when hardware is available).
- Tests pass with local backend mocked.
