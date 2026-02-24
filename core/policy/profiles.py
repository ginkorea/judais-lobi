# core/policy/profiles.py — Profile → PolicyPack mapping

from typing import Dict, List

from core.contracts.schemas import PolicyPack, ProfileMode


# Each profile level defines *additional* scopes beyond the previous level.
# policy_for_profile() accumulates scopes up to the requested level.
PROFILE_SCOPES: Dict[ProfileMode, List[str]] = {
    ProfileMode.SAFE: [
        "fs.read",
        "git.read",
        "verify.run",
    ],
    ProfileMode.DEV: [
        "fs.write",
        "git.write",
        "python.exec",
        "shell.exec",
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
