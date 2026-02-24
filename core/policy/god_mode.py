# core/policy/god_mode.py — God mode with TTL + panic switch

import threading
from typing import Optional

from core.contracts.schemas import AuditEntry, GodModeGrant, ProfileMode
from core.policy.audit import AuditLogger
from core.tools.capability import CapabilityEngine


class GodModeSession:
    """Manages god mode activation with mandatory reason, TTL, and panic switch.

    - ``activate()`` sets profile to GOD, starts a TTL timer
    - ``panic()`` immediately downgrades to SAFE and revokes all grants
    - TTL expiry auto-downgrades to DEV
    """

    def __init__(self, audit: AuditLogger):
        self._audit = audit
        self._grant: Optional[GodModeGrant] = None
        self._panic = threading.Event()
        self._timer: Optional[threading.Timer] = None

    @property
    def grant(self) -> Optional[GodModeGrant]:
        return self._grant

    def is_active(self) -> bool:
        """True if god mode is currently active and not expired/panicked."""
        if self._grant is None:
            return False
        if self._grant.panic_revoked:
            return False
        if self._panic.is_set():
            return False
        # Check if timer is still alive (not expired)
        if self._timer is not None and not self._timer.is_alive():
            return False
        return True

    def activate(
        self,
        reason: str,
        ttl: float = 300.0,
        capability_engine: Optional[CapabilityEngine] = None,
    ) -> GodModeGrant:
        """Activate god mode.

        Parameters
        ----------
        reason : str
            Mandatory reason for activation (audit trail).
        ttl : float
            Time-to-live in seconds. After expiry, auto-downgrades to DEV.
        capability_engine : CapabilityEngine, optional
            If provided, profile is set to GOD immediately.
        """
        # Cancel any existing timer
        if self._timer is not None:
            self._timer.cancel()

        self._panic.clear()
        self._grant = GodModeGrant(reason=reason, ttl_seconds=ttl)

        if capability_engine is not None:
            capability_engine.set_profile(ProfileMode.GOD)

        self._timer = threading.Timer(
            ttl, self._auto_downgrade, args=[capability_engine],
        )
        self._timer.daemon = True
        self._timer.start()

        self._audit.log(AuditEntry(
            event_type="god_activate",
            detail=reason,
            profile="god",
            verdict="allowed",
        ))
        return self._grant

    def panic(self, capability_engine: Optional[CapabilityEngine] = None) -> None:
        """Immediate kill switch.

        - Sets panic event (checked by ToolBus before every dispatch)
        - Cancels TTL timer
        - Marks grant as panic_revoked
        - Downgrades to SAFE and revokes all grants
        """
        self._panic.set()

        if self._timer is not None:
            self._timer.cancel()

        if self._grant is not None:
            self._grant.panic_revoked = True

        if capability_engine is not None:
            capability_engine.set_profile(ProfileMode.SAFE)
            capability_engine.revoke_all_grants()

        self._audit.log(AuditEntry(
            event_type="panic",
            profile="safe",
            verdict="panic_revoked",
        ))

    @property
    def is_panicked(self) -> bool:
        """True if the panic switch has been activated."""
        return self._panic.is_set()

    def _auto_downgrade(self, capability_engine: Optional[CapabilityEngine] = None) -> None:
        """Called by timer when TTL expires. Downgrades to DEV."""
        if self._panic.is_set():
            return  # Already panicked, don't override

        if capability_engine is not None:
            capability_engine.set_profile(ProfileMode.DEV)

        self._audit.log(AuditEntry(
            event_type="god_expire",
            profile="dev",
            verdict="allowed",
        ))
