# 1.6.0 published-contract correction

Base: `db6ba712`, the integrated 1.6.0 release candidate. This correction changes
no execution behavior: the five existing task-state options become published
`CLI_FLAGS`, and README, CONTRACT, PLATFORMS and the shipped conformance-kit
table name the supported surface accurately. The version remains 1.6.0.

The parent integration gate reported 824 passes and 10 failures before this
correction. Missing documentation covered deferred/active skills, the output
profile, history/receipt/task provenance, and task flags described by PLATFORMS
but absent from the published CLI contract. Inspection additionally found the
shipped conformance template missing the corresponding optional fields, flags
and environment variable. Its maximal equality checks remain unchanged: no
allowlist or exemption was added. Existing CLI/library receipt parity assertions
also remain unchanged. Six new contract cases assert task-flag publication and
the parser's owner/thread strings, pointer paths and opt-out boolean.

## Verified candidate

Interpreter: `/home/gompert/.conda/envs/iq/bin/python`, Python 3.13.14,
pytest 9.1.1. Recon printed `core.runtime.contract.__file__` under the isolated
`TAIPAN/.worktrees/judais-release-contract` tree before execution. Absolute
`PYTHONPATH` kept subprocesses on that same checkout. The copied conformance kit
also reported that exact source and schema version 1.

The sequential frozen candidate passed **988 tests, zero failures and zero
skips**, in **315.99 seconds**. One existing copied-kit class-scoped fixture
produced a pytest-10 deprecation warning. The process exited zero before the
pytest slot was released to the installer lane. No live credentials or model
calls were used. Local scripted/localhost fixtures required ordinary approved
execution outside the socket-restricted sandbox.

Modules:

```text
tests/test_packaging.py
tests/test_contract.py
tests/test_docs_track_the_code.py
tests/test_platforms_doc.py
tests/test_conformance_kit.py
tests/conformance/test_conformance.py
tests/test_facade.py
tests/test_cli_mission_skill.py
tests/test_task_state.py
tests/test_output_profiles.py
```

Command shape: `timeout 420 <interpreter> -m pytest <modules> -q -ra --tb=short
--show-capture=no -p no:cacheprovider -o addopts=`, with unique private basetemp
and JUnit report under `TAIPAN/.operator/release-contract-pytest`. `TMPDIR` used
that same private parent for subprocess fixtures. The invocation removed
`TAIPAN_TOKEN`, `TAIPAN_COGNITO_ACCESS_TOKEN`, `JUDAIS_LOBI_OUTPUT_PROFILE` and
`JUDAIS_LOBI_MAX_OUTPUT_TOKENS` from the test environment. Private JUnit report:
`candidate.xml`; terminal process handle: 86280.

Ruff and diff-whitespace checks pass on the changed contract/tests. The changed
contract module passes mypy with `--follow-imports=skip --ignore-missing-imports
--no-incremental` and no issues. This is
source verification, not a deployment, package publication or live acceptance.
Any subsequent runtime integration requires its own final release gate.
