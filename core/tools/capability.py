# core/tools/capability.py — Deny-by-default capability engine

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from core.contracts.schemas import PermissionGrant, PolicyPack

if TYPE_CHECKING:
    from core.contracts.schemas import ProfileMode


@dataclass
class CapabilityVerdict:
    """Result of a capability check."""
    allowed: bool
    denied_scopes: List[str] = field(default_factory=list)
    reason: str = ""


class CapabilityEngine:
    """Deny-by-default capability checker.

    Checks tool invocations against:
    1. PolicyPack (static session-level permissions)
    2. Active PermissionGrants (dynamic, possibly time-scoped)

    Supports wildcard ``"*"`` in ``allowed_scopes`` — grants all scopes.
    """

    def __init__(self, policy: Optional[PolicyPack] = None):
        self._policy = policy or PolicyPack()
        self._grants: List[PermissionGrant] = []
        self._current_profile: Optional[str] = None
        self._scope_constraints: Optional[set] = None

    @property
    def policy(self) -> PolicyPack:
        return self._policy

    @property
    def current_profile(self) -> Optional[str]:
        return self._current_profile

    def add_grant(self, grant: PermissionGrant) -> None:
        """Add a permission grant."""
        self._grants.append(grant)

    def check(self, tool_name: str, required_scopes: List[str]) -> CapabilityVerdict:
        """Check if all required scopes are satisfied by policy or active grants.

        Returns CapabilityVerdict(allowed=True) only if ALL required scopes
        are covered. Invocation-scoped grants are consumed on successful check.
        """
        if not required_scopes:
            return CapabilityVerdict(allowed=True, reason="no scopes required")

        # First, expire stale grants
        self.expire_stale_grants()

        denied = []
        invocation_grants_to_consume = []

        for scope in required_scopes:
            if self._scope_constraints is not None and scope not in self._scope_constraints:
                denied.append(scope)
                continue
            if self._is_scope_in_policy(scope):
                continue
            grant = self._find_active_grant(tool_name, scope)
            if grant is None:
                denied.append(scope)
            elif grant.grant_scope == "invocation":
                invocation_grants_to_consume.append(grant)

        if denied:
            return CapabilityVerdict(
                allowed=False,
                denied_scopes=denied,
                reason=f"denied scopes: {', '.join(denied)}",
            )

        # Consume invocation-scoped grants
        for grant in invocation_grants_to_consume:
            if grant in self._grants:
                self._grants.remove(grant)

        return CapabilityVerdict(allowed=True, reason="all scopes granted")

    def is_scope_granted(self, tool_name: str, scope: str) -> bool:
        """Check if a single scope is granted (by policy or active grant)."""
        if self._scope_constraints is not None and scope not in self._scope_constraints:
            return False
        if self._is_scope_in_policy(scope):
            return True
        return self._find_active_grant(tool_name, scope) is not None

    def set_scope_constraints(self, scopes: Optional[List[str]]) -> None:
        """Set an allowlist of scopes to intersect with policy/grants."""
        if scopes is None:
            self._scope_constraints = None
            return
        self._scope_constraints = set(scopes)

    def clear_scope_constraints(self) -> None:
        """Clear any scope constraints."""
        self._scope_constraints = None

    @property
    def scope_constraints(self) -> Optional[List[str]]:
        if self._scope_constraints is None:
            return None
        return list(self._scope_constraints)

    def list_active_grants(self) -> List[PermissionGrant]:
        """Return all non-expired grants."""
        self.expire_stale_grants()
        return list(self._grants)

    def expire_stale_grants(self) -> int:
        """Remove time-expired grants. Returns count of expired grants."""
        now = datetime.now(timezone.utc)
        expired = []
        for grant in self._grants:
            if grant.grant_duration_seconds is not None:
                expiry = grant.grant_issued_at.timestamp() + grant.grant_duration_seconds
                if now.timestamp() > expiry:
                    expired.append(grant)
        for grant in expired:
            self._grants.remove(grant)
        return len(expired)

    def load_grants(self, grants: List[PermissionGrant]) -> None:
        """Bulk-load grants for session replay.

        Replaces existing grants. Does not evaluate wall clock for
        time-scoped grants during replay — they are loaded as-is.
        """
        self._grants = list(grants)

    def revoke_all_grants(self) -> int:
        """Revoke all active grants. Returns the count of revoked grants."""
        count = len(self._grants)
        self._grants.clear()
        return count

    def set_profile(self, profile: "ProfileMode") -> None:
        """Replace the internal policy with one derived from *profile*.

        Requires ``core.policy.profiles.policy_for_profile`` — imported
        lazily to avoid circular imports.
        """
        from core.policy.profiles import policy_for_profile
        self._policy = policy_for_profile(profile)
        self._current_profile = profile.value

    def _is_scope_in_policy(self, scope: str) -> bool:
        """Check if scope is allowed by the static policy.

        Supports wildcard ``"*"`` — if present, all scopes are allowed.
        """
        if "*" in self._policy.allowed_scopes:
            return True
        return scope in self._policy.allowed_scopes

    def _find_active_grant(self, tool_name: str, scope: str) -> Optional[PermissionGrant]:
        """Find a matching non-expired grant for tool_name + scope."""
        now = datetime.now(timezone.utc)
        for grant in self._grants:
            if grant.scope != scope:
                continue
            # Grant can be tool-specific or wildcard (empty tool_name)
            if grant.tool_name and grant.tool_name != tool_name:
                continue
            # Check time expiry
            if grant.grant_duration_seconds is not None:
                expiry = grant.grant_issued_at.timestamp() + grant.grant_duration_seconds
                if now.timestamp() > expiry:
                    continue
            return grant
        return None
