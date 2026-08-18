# tests/test_kernel_budgets.py — Tests for budget config and enforcement
#
# And, from the bottom of the file, for `core.budgets` — the module the
# kernel and the mission loop now share. It is asserted here rather than in
# a file of its own because the thing worth asserting is that there is ONE
# of it: a test that only ever imported `core.budgets` could not notice the
# day the kernel grew a second `BudgetExhausted` back.

import time
import pytest
from dataclasses import FrozenInstanceError

import core.budgets as shared
from core.budgets import Budgets, Cancellation, Deadline, WHICH, cancelled
from core.kernel.state import Phase, SessionState
from core.kernel.budgets import (
    BudgetConfig,
    BudgetExhausted,
    PhaseRetriesExhausted,
    check_phase_retries,
    check_total_iterations,
    check_phase_time,
    check_all_budgets,
)


class _Clock:
    """A monotonic that moves only when a test says so.

    Injected into :class:`Deadline` so that proving a run stops at its
    deadline costs no wall-clock seconds.  A test that slept for its own
    budget would be a slow test *and* a flaky one — the thing it asserts
    is the comparison, not the sleeping.
    """

    def __init__(self, start: float = 1_000.0):
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class TestBudgetConfig:
    def test_defaults(self):
        config = BudgetConfig()
        assert config.max_phase_retries == 3
        assert config.max_total_iterations == 30
        assert config.max_time_per_phase_seconds == 300.0
        assert config.max_tool_output_bytes_in_context == 32_768
        assert config.max_context_tokens_per_role == 16_384
        assert config.max_candidates == 5

    def test_frozen(self):
        config = BudgetConfig()
        with pytest.raises(FrozenInstanceError):
            config.max_phase_retries = 10

    def test_custom_values(self):
        config = BudgetConfig(
            max_phase_retries=5,
            max_total_iterations=100,
            max_time_per_phase_seconds=60.0,
        )
        assert config.max_phase_retries == 5
        assert config.max_total_iterations == 100
        assert config.max_time_per_phase_seconds == 60.0

    def test_max_candidates_default(self):
        config = BudgetConfig()
        assert config.max_candidates == 5

    def test_max_candidates_custom(self):
        config = BudgetConfig(max_candidates=10)
        assert config.max_candidates == 10

    def test_max_candidates_frozen(self):
        config = BudgetConfig()
        with pytest.raises(FrozenInstanceError):
            config.max_candidates = 3


class TestCheckPhaseRetries:
    def test_under_limit_no_raise(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        config = BudgetConfig(max_phase_retries=3)
        check_phase_retries(state, config)  # Should not raise

    def test_at_limit_raises(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        state.phase_retries[Phase.CONTRACT] = 3
        config = BudgetConfig(max_phase_retries=3)
        with pytest.raises(PhaseRetriesExhausted):
            check_phase_retries(state, config)

    def test_over_limit_raises(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        state.phase_retries[Phase.CONTRACT] = 5
        config = BudgetConfig(max_phase_retries=3)
        with pytest.raises(PhaseRetriesExhausted):
            check_phase_retries(state, config)

    def test_exception_attributes(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        state.phase_retries[Phase.CONTRACT] = 3
        config = BudgetConfig(max_phase_retries=3)
        with pytest.raises(PhaseRetriesExhausted) as exc_info:
            check_phase_retries(state, config)
        assert exc_info.value.phase == Phase.CONTRACT
        assert exc_info.value.retries == 3
        assert exc_info.value.max_retries == 3


class TestCheckTotalIterations:
    def test_under_limit_no_raise(self):
        state = SessionState(task_description="test")
        state.total_iterations = 10
        config = BudgetConfig(max_total_iterations=30)
        check_total_iterations(state, config)  # Should not raise

    def test_at_limit_raises(self):
        state = SessionState(task_description="test")
        state.total_iterations = 30
        config = BudgetConfig(max_total_iterations=30)
        with pytest.raises(BudgetExhausted):
            check_total_iterations(state, config)

    def test_exception_names_the_steps_budget(self):
        """Folded into `Bounds`' vocabulary: the kernel no longer raises a
        `TotalIterationsExhausted` of its own, it raises the shared
        `BudgetExhausted` naming `steps` — the word a mission stream carries
        for the same fact. `limit`/`spent` are the cap and what was spent."""
        state = SessionState(task_description="test")
        state.total_iterations = 30
        config = BudgetConfig(max_total_iterations=30)
        with pytest.raises(BudgetExhausted) as exc_info:
            check_total_iterations(state, config)
        assert exc_info.value.which == "steps"
        assert exc_info.value.limit == 30
        assert exc_info.value.spent == 30


class TestCheckPhaseTime:
    def test_within_limit_no_raise(self):
        state = SessionState(task_description="test")
        state.phase_start_time = time.monotonic()  # Just started
        config = BudgetConfig(max_time_per_phase_seconds=300.0)
        check_phase_time(state, config)  # Should not raise

    def test_over_limit_raises(self):
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        # Simulate phase started 400 seconds ago
        state.phase_start_time = time.monotonic() - 400.0
        config = BudgetConfig(max_time_per_phase_seconds=300.0)
        with pytest.raises(BudgetExhausted) as exc_info:
            check_phase_time(state, config)
        # Folded into `Bounds`' vocabulary: `seconds`, not a kernel subclass.
        assert exc_info.value.which == "seconds"
        assert exc_info.value.limit == 300.0

    def test_no_start_time_no_raise(self):
        state = SessionState(task_description="test")
        state.phase_start_time = None
        config = BudgetConfig(max_time_per_phase_seconds=1.0)
        check_phase_time(state, config)  # Should not raise


class TestCheckAllBudgets:
    def test_all_under_limit(self):
        state = SessionState(task_description="test")
        config = BudgetConfig()
        check_all_budgets(state, config)  # Should not raise

    def test_iterations_checked_first(self):
        """When both iterations and retries are exceeded, the `steps`
        exhaustion fires first — and it is the shared `BudgetExhausted`, not
        a retries one, so `which` tells them apart."""
        state = SessionState(task_description="test")
        state.enter_phase(Phase.CONTRACT)
        state.total_iterations = 30
        state.phase_retries[Phase.CONTRACT] = 5
        config = BudgetConfig(max_total_iterations=30, max_phase_retries=3)
        with pytest.raises(BudgetExhausted) as exc_info:
            check_all_budgets(state, config)
        assert exc_info.value.which == "steps"


class TestExceptionHierarchy:
    def test_the_one_kernel_subclass_still_subclasses_budget_exhausted(self):
        """`retries` is the only budget the kernel has that a mission does
        not, so `PhaseRetriesExhausted` is the only subclass this module
        keeps. `steps` and `seconds` are raised as the shared
        `BudgetExhausted` itself — folded into `Bounds`' vocabulary."""
        assert issubclass(PhaseRetriesExhausted, BudgetExhausted)

    def test_catch_base_catches_all(self):
        """except BudgetExhausted catches the retries subclass and the
        shared steps/seconds exceptions alike."""
        exceptions = [
            PhaseRetriesExhausted(Phase.INTAKE, 3, 3),
            BudgetExhausted("steps", 30, 30),
            BudgetExhausted("seconds", 300.0, 400.0),
        ]
        for exc in exceptions:
            try:
                raise exc
            except BudgetExhausted:
                pass  # Expected


# ── one owner: the shape, the words and the exception both runtimes use ──────


class TestThereIsOneBudgetExhausted:
    """The kernel declared its own base class until a mission grew a wall
    clock; two runtimes with two `BudgetExhausted`es is the shape of a
    `except` clause that silently stops catching half of what it meant to.
    """

    def test_the_kernel_re_exports_the_shared_class_rather_than_a_copy(self):
        assert BudgetExhausted is shared.BudgetExhausted

    def test_a_mission_budget_is_caught_by_the_kernels_except_clause(self):
        try:
            raise shared.BudgetExhausted("seconds", 30.0, 31.2)
        except BudgetExhausted as exc:
            assert exc.which == "seconds"

    @pytest.mark.parametrize("exc,which,limit,spent", [
        (PhaseRetriesExhausted(Phase.INTAKE, 3, 3), "retries", 3, 3),
        (BudgetExhausted("steps", 30, 30), "steps", 30, 30),
        (BudgetExhausted("seconds", 300.0, 400.0), "seconds", 300.0, 400.0),
    ])
    def test_every_kernel_violation_names_its_budget(
            self, exc, which, limit, spent):
        """`which`/`limit`/`spent` read the same off either runtime's
        exception. An iteration and a step are the same thing under two
        names, and only one of the two names is the one a consumer of the
        mission stream was told to expect — so the kernel now raises that
        one directly for `steps` and `seconds`, keeping only `retries` as
        its own."""
        assert (exc.which, exc.limit, exc.spent) == (which, limit, spent)

    def test_the_kernel_keeps_its_own_attributes_too(self):
        """The shared base is an addition, not a replacement: callers read
        `exc.phase` and `exc.max_retries`."""
        exc = PhaseRetriesExhausted(Phase.CONTRACT, 3, 3)
        assert exc.phase == Phase.CONTRACT and exc.max_retries == 3
        assert "CONTRACT" in str(exc)

    def test_only_the_missions_words_are_in_the_wire_vocabulary(self):
        """`retries` is a real budget and deliberately NOT in `WHICH`: the
        kernel has phases and a mission does not, and a word a
        `mission_finished` can never carry has no business in the closed set
        a consumer switches on."""
        assert WHICH == ("steps", "seconds", "bytes", "tokens")
        assert "retries" not in WHICH


class TestTheSharedBudgetShape:
    def test_every_budget_is_unbounded_by_default(self):
        """None and not zero, and not some number nobody chose. A framework
        that killed a slow local model at a default would be a regression
        wearing a safety net's clothes."""
        budgets = Budgets()
        assert (budgets.max_steps, budgets.max_seconds,
                budgets.max_bytes, budgets.max_tokens) == (None, None, None, None)

    def test_the_console_line_names_the_unbounded_ones_as_unbounded(self):
        """Both absences printed, and the steps one says CEILING: nothing
        counts a run's turns any more, so "unbounded steps" would describe
        a thing that no longer has a bounded form to be the opposite of."""
        assert Budgets(max_steps=8).describe() == "8 steps, no wall clock"
        assert Budgets(max_steps=8, max_seconds=90).describe() == "8 steps, 90 s"
        assert Budgets().describe() == "no step ceiling, no wall clock"

    def test_the_exception_renders_the_field_a_consumer_indexes(self):
        exhausted = shared.BudgetExhausted("steps", 8, 8)
        assert exhausted.as_record() == {"which": "steps", "limit": 8, "spent": 8}


class TestTheDeadline:
    def test_a_clock_nobody_wound_has_spent_nothing(self):
        """An unstarted deadline never expires. A runner constructed now and
        run in ten minutes must not begin already over."""
        clock = _Clock()
        deadline = Deadline(5.0, monotonic=clock)
        clock.advance(600)
        assert deadline.spent() == 0.0
        assert deadline.expired() is False
        assert deadline.exhausted() is None

    def test_an_unbounded_deadline_never_expires(self):
        clock = _Clock()
        deadline = Deadline(None, monotonic=clock).start()
        clock.advance(10_000)
        assert deadline.unbounded is True
        assert deadline.remaining() is None
        assert deadline.expired() is False

    def test_the_first_start_wins(self):
        """The whole reason a staged mission can share one clock: five
        sub-missions of a minute each must not fit inside a one-minute
        budget."""
        clock = _Clock()
        deadline = Deadline(60.0, monotonic=clock).start()
        clock.advance(45)
        deadline.start()
        deadline.start()
        assert deadline.spent() == 45.0
        assert deadline.remaining() == 15.0

    def test_it_expires_and_says_what_it_spent(self):
        clock = _Clock()
        deadline = Deadline(30.0, monotonic=clock).start()
        clock.advance(31.5)
        exhausted = deadline.exhausted()
        assert exhausted is not None
        assert exhausted.which == "seconds"
        assert exhausted.limit == 30.0
        # Not the limit: a wall clock is noticed a little after it runs out,
        # and reporting the limit as the spend would hide by how much.
        assert exhausted.spent == 31.5

    def test_remaining_goes_negative_rather_than_flattering_the_caller(self):
        clock = _Clock()
        deadline = Deadline(10.0, monotonic=clock).start()
        clock.advance(12)
        assert deadline.remaining() == -2.0

    def test_of_reads_the_budget_off_the_shape(self):
        assert Deadline.of(Budgets(max_seconds=12.5)).seconds == 12.5
        assert Deadline.of(Budgets()).seconds is None


class TestTheCancellation:
    def test_it_starts_unset(self):
        assert Cancellation().is_set() is False
        assert bool(Cancellation()) is False

    def test_throwing_it_sticks(self):
        switch = Cancellation()
        switch.cancel("sigterm")
        assert switch.is_set() is True and switch.cause == "sigterm"

    def test_the_first_cause_wins(self):
        """A second signal does not rewrite why the first one happened —
        which matters because the cause decides whether this process still
        owes somebody an exit status."""
        switch = Cancellation()
        switch.cancel("sigterm")
        switch.cancel("something else")
        assert switch.cause == "sigterm"

    def test_the_helper_reads_anything_with_is_set(self):
        """A caller holding a bare `threading.Event` should not have to wrap
        it, and `None` — the default everywhere — is not cancelled."""
        import threading

        event = threading.Event()
        assert cancelled(None) is False
        assert cancelled(event) is False
        event.set()
        assert cancelled(event) is True
        assert cancelled(Cancellation()) is False

    def test_a_watcher_that_throws_does_not_stop_a_run(self):
        class Broken:
            def is_set(self):
                raise RuntimeError("no")

        assert cancelled(Broken()) is False
