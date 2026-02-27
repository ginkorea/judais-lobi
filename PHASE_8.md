# Phase 8 Plan — Retrieval, Context Discipline & Local Inference

**Status:** Planned (no GPU available for local inference testing).

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
