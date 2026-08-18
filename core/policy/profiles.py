# core/policy/profiles.py — Profile → PolicyPack mapping

import os
from typing import Dict, List, Optional

from core.contracts.schemas import PolicyPack, ProfileMode


#: The profile a run gets when nothing opts up.  Phase 1's deny-by-default:
#: read the filesystem, read git, run the verifiers, and call out to an MCP
#: server the operator explicitly connected — nothing that writes, executes
#: or reaches the open network.
DEFAULT_PROFILE = ProfileMode.SAFE

#: The environment variable that opts a run up from :data:`DEFAULT_PROFILE`.
#: A flag beats it; see :func:`select_profile`.
PROFILE_ENV_VAR = "JUDAIS_LOBI_PROFILE"


# Each profile level defines *additional* scopes beyond the previous level.
# policy_for_profile() accumulates scopes up to the requested level.
PROFILE_SCOPES: Dict[ProfileMode, List[str]] = {
    ProfileMode.SAFE: [
        "fs.read",
        "git.read",
        "verify.run",
        # `mcp.call` lives here, in the *lowest* profile, on purpose. It is
        # the one scope every bridged MCP tool carries
        # (`McpToolBridge.DEFAULT_SCOPES`), and the decision it expresses is
        # "may this agent call out to this server at all" — not "may it run
        # this particular tool". Two things already gate the latter: the
        # skill manifest's closed set (the mission is offered only the tools
        # the author named) and the server's own principal-based
        # authorization (a bridged call is authenticated as the mission's
        # principal and refused per-tool at the far end). So `mcp.call`
        # under a *deny-by-default* SAFE gates nothing the manifest and the
        # server do not already gate, and holding it back would only break
        # `--mission` under the default while adding no safety — the operator
        # already chose the plane by passing `--mcp-stdio`/`--mcp-url`.
        # Without it here, `mcp.call` would sit in no profile at all and be
        # unreachable even under `ops`, which is the bug this line fixes.
        "mcp.call",
        # Reading memory is SAFE for the same reason reading the filesystem
        # is: it reaches nothing this deployment was not already told. A
        # recall returns notes this harness itself distilled from runs it
        # already made, out of a directory an operator named — no network,
        # no new data, and a hard token budget on what comes back. Writing
        # is the other half and it is in DEV, below.
        "memory.read",
    ],
    ProfileMode.DEV: [
        "fs.write",
        "git.write",
        "python.exec",
        "shell.exec",
        # A memory write is a DURABLE effect on later runs — a block pinned
        # into every future system turn of this principal — so it sits with
        # `fs.write` and not with the read. The asymmetry is the point: a
        # run under the default profile may consult what it knows and may
        # not change what it will be told next time.
        "memory.write",
    ],
    ProfileMode.OPS: [
        "git.push",
        "git.fetch",
        "pip.install",
        "http.read",
        "fs.delete",
        "audio.output",
    ],
    ProfileMode.GOD: ["*"],
}


def policy_for_profile(profile: ProfileMode) -> PolicyPack:
    """Build a PolicyPack with accumulated scopes up to *profile* level.

    Each level includes all scopes from lower levels.  GOD adds the
    wildcard ``"*"`` which the CapabilityEngine interprets as allow-all.
    """
    scopes: List[str] = []
    for level in ProfileMode:
        scopes.extend(PROFILE_SCOPES[level])
        if level == profile:
            break
    return PolicyPack(allowed_scopes=sorted(set(scopes)))


def select_profile(requested: Optional[str] = None) -> ProfileMode:
    """Resolve the effective :class:`ProfileMode`: flag > env > default.

    *requested* is the ``--profile`` flag value (``None`` when unset). When
    it is ``None`` the ``JUDAIS_LOBI_PROFILE`` environment variable is
    consulted, and when that too is unset the run gets
    :data:`DEFAULT_PROFILE` (``SAFE``). A flag therefore always beats the
    environment, and the environment always beats the default — the one
    resolution the CLI and any library caller share, so the precedence is
    stated once.

    Named ``select_profile`` and not ``resolve_profile`` deliberately:
    ``core.runtime.context_window`` already owns an unrelated
    ``resolve_profile`` (a context-window sizing decision), and two
    functions of the same name doing different jobs is the kind of near-miss
    this framework spends refusals to avoid.

    A value that names no profile is a :class:`ValueError` that lists the
    choices — a refusal at the door, not a silent fall-through to SAFE under
    an operator who typed ``--profile dveloper`` and believes they opted up.
    """
    candidate = requested if requested is not None else os.getenv(PROFILE_ENV_VAR)
    if candidate is None or not str(candidate).strip():
        return DEFAULT_PROFILE
    try:
        return ProfileMode(str(candidate).strip().lower())
    except ValueError:
        valid = ", ".join(mode.value for mode in ProfileMode)
        raise ValueError(
            f"unknown profile {candidate!r}; choose one of: {valid}"
        )


def lowest_profile_for_scope(scope: str) -> Optional[ProfileMode]:
    """The lowest :class:`ProfileMode` whose scopes include *scope*.

    Walks the profiles from SAFE upward and returns the first level at
    which *scope* becomes granted. A scope named literally in some level's
    :data:`PROFILE_SCOPES` resolves to that level; a scope named in no level
    is reachable only through GOD's wildcard ``"*"`` and resolves to
    ``GOD``. Returns ``None`` only if *scope* is falsy.

    This is the single source for "which profile grants this?", so a
    refusal that names the fix (see :func:`scope_grant_hint`) cannot drift
    from the table that decides the grant.
    """
    if not scope:
        return None
    for level in ProfileMode:
        level_scopes = PROFILE_SCOPES.get(level, [])
        if scope in level_scopes:
            return level
        if "*" in level_scopes:
            # The wildcard level (GOD) grants everything that no earlier,
            # explicit level named. Reaching here means the scope is not
            # placed in any narrower profile.
            return level
    return None


def scope_grant_hint(scope: str) -> str:
    """One clause naming how to grant *scope*, or ``""`` for a default scope.

    ``"shell.exec"`` → ``"--profile dev (or JUDAIS_LOBI_PROFILE=dev)"``.

    A scope already in :data:`DEFAULT_PROFILE` returns ``""``: there is
    nothing to opt into, and a refusal for such a scope is never about the
    profile. Derived from :func:`lowest_profile_for_scope` so the named
    profile is always the *lowest* one that grants it, and always the one
    the table actually uses.
    """
    level = lowest_profile_for_scope(scope)
    if level is None or level == DEFAULT_PROFILE:
        return ""
    return f"--profile {level.value} (or {PROFILE_ENV_VAR}={level.value})"


def denial_reason(denied_scopes: List[str],
                  current_profile: Optional[str] = None) -> str:
    """A refusal sentence that names each missing scope and its fix.

    Given the scopes a :class:`~core.tools.capability.CapabilityEngine`
    denied and the name of the profile in force, returns a sentence a model
    or a person can act on directly — the missing scope and the *lowest*
    ``--profile`` (or ``JUDAIS_LOBI_PROFILE``) that grants it. This is the
    text the ToolBus renders into a ``capability_denied`` message, so the
    message names the fix rather than only the fault.

    A scope that no profile below GOD grants is reported as needing
    ``--profile god`` all the same; a scope already in the default profile
    (which should not be denied unless a constraint narrowed it) is named
    without a profile clause.
    """
    under = f" under profile '{current_profile}'" if current_profile else ""
    parts: List[str] = []
    for scope in denied_scopes:
        hint = scope_grant_hint(scope)
        if hint:
            parts.append(f"{scope} needs {hint}")
        else:
            parts.append(scope)
    joined = "; ".join(parts) if parts else "(no scopes named)"
    return f"denied{under}: {joined}"
