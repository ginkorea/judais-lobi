# tests/test_config_loader.py — Config loader tests

import pytest
from core.tools.config_loader import load_pricing, load_project_config


class TestConfigLoader:
    def test_returns_empty_when_no_config(self, tmp_path):
        result = load_project_config(tmp_path)
        assert result == {}

    def test_loads_yml_file(self, tmp_path):
        config_file = tmp_path / ".judais-lobi.yml"
        config_file.write_text("verification:\n  lint: custom_lint\n")
        result = load_project_config(tmp_path)
        assert result["verification"]["lint"] == "custom_lint"

    def test_loads_yaml_extension(self, tmp_path):
        config_file = tmp_path / ".judais-lobi.yaml"
        config_file.write_text("verification:\n  test: custom_test\n")
        result = load_project_config(tmp_path)
        assert result["verification"]["test"] == "custom_test"

    def test_yml_takes_precedence(self, tmp_path):
        (tmp_path / ".judais-lobi.yml").write_text("source: yml\n")
        (tmp_path / ".judais-lobi.yaml").write_text("source: yaml\n")
        result = load_project_config(tmp_path)
        assert result["source"] == "yml"

    def test_empty_file_returns_empty(self, tmp_path):
        (tmp_path / ".judais-lobi.yml").write_text("")
        result = load_project_config(tmp_path)
        assert result == {}

    def test_invalid_yaml_returns_empty(self, tmp_path):
        (tmp_path / ".judais-lobi.yml").write_text(": : :\n  bad yaml {{[")
        result = load_project_config(tmp_path)
        assert result == {}


PRICING = """\
pricing:
  openai:
    gpt-4o-mini:
      prompt_per_1k: 0.15
      completion_per_1k: 0.6
    "*":
      prompt_per_1k: 1.0
      completion_per_1k: 2.0
  local:
    my-served-model:
      prompt_per_1k: 0.002
      completion_per_1k: 0.002
      currency: EUR
"""


class TestThePricingBlock:
    """The only place a price may come from.

    There is no price list in this repository and there must not be one:
    prices move, they differ per account, and a framework that shipped a
    number would be quoting a figure it cannot know. So the block is
    optional, its absence is the normal case, and every way of getting it
    wrong ends in "no cost" rather than in a wrong one.
    """

    def test_no_config_is_no_pricing(self, tmp_path):
        assert load_pricing(tmp_path) == {}

    def test_a_config_without_the_block_is_no_pricing(self, tmp_path):
        (tmp_path / ".judais-lobi.yml").write_text("verification:\n  lint: x\n")
        assert load_pricing(tmp_path) == {}

    def test_the_block_is_read(self, tmp_path):
        (tmp_path / ".judais-lobi.yml").write_text(PRICING)
        assert load_pricing(tmp_path)["openai"]["gpt-4o-mini"][
            "prompt_per_1k"] == 0.15

    def test_a_block_that_is_not_a_mapping_is_no_pricing(self, tmp_path):
        """A typo in optional decoration must not cost anybody a mission."""
        (tmp_path / ".judais-lobi.yml").write_text("pricing: cheap\n")
        assert load_pricing(tmp_path) == {}


class TestThePricingTableFindsARate:
    def _table(self, tmp_path, text=PRICING):
        from core.runtime.usage import PricingTable

        (tmp_path / ".judais-lobi.yml").write_text(text)
        return PricingTable.from_project(tmp_path)

    def test_an_exact_provider_and_model(self, tmp_path):
        rate = self._table(tmp_path).rate_for("openai", "gpt-4o-mini")
        assert (rate.prompt_per_1k, rate.completion_per_1k) == (0.15, 0.6)

    def test_the_currency_defaults_to_usd_and_is_kept_when_stated(self, tmp_path):
        table = self._table(tmp_path)
        assert table.rate_for("openai", "gpt-4o-mini").currency == "USD"
        assert table.rate_for("local", "my-served-model").currency == "EUR"

    def test_a_star_entry_covers_a_model_nobody_named(self, tmp_path):
        """One priced endpoint under whatever name the server advertises
        this week."""
        rate = self._table(tmp_path).rate_for("openai", "gpt-4o-2099")
        assert rate.prompt_per_1k == 1.0

    def test_an_unpriced_provider_has_no_rate(self, tmp_path):
        assert self._table(tmp_path).rate_for("mistral", "codestral") is None

    def test_a_local_model_nobody_priced_has_no_rate(self, tmp_path):
        """`local` has no cost unless somebody configured one. The
        electricity is real and this harness has no idea what it costs."""
        assert self._table(tmp_path).rate_for("local", "gpt-oss-20b") is None

    def test_no_table_at_all_never_finds_a_rate(self, tmp_path):
        from core.runtime.usage import PricingTable

        table = PricingTable.from_project(tmp_path)
        assert not table
        assert table.rate_for("openai", "gpt-4o-mini") is None

    def test_an_entry_with_no_numbers_is_dropped_rather_than_zeroed(
            self, tmp_path):
        """A zero rate reports a run as free, and "free" is a claim nobody
        made."""
        table = self._table(
            tmp_path, "pricing:\n  openai:\n    m:\n      note: ask finance\n")
        assert table.rate_for("openai", "m") is None

    def test_the_provider_name_is_matched_case_insensitively(self, tmp_path):
        assert self._table(tmp_path).rate_for("OpenAI", "gpt-4o-mini") is not None


class TestARatePricesALedger:
    def test_the_two_halves_are_priced_separately(self):
        from core.runtime.usage import Ledger, Rate
        from core.runtime.backends.base import Usage

        ledger = Ledger()
        ledger.add(Usage(prompt_tokens=2000, completion_tokens=1000,
                         total_tokens=3000))
        rate = Rate(prompt_per_1k=0.5, completion_per_1k=2.0)
        assert rate.cost_of(ledger) == {"amount": 3.0, "currency": "USD"}

    def test_an_empty_ledger_has_no_cost_rather_than_a_zero_one(self):
        from core.runtime.usage import Ledger, Rate

        assert Rate(prompt_per_1k=1.0).cost_of(Ledger()) is None


class TestTheLedgerCountsOnlyRealReports:
    """The source is a caller-supplied callable reading a caller-supplied
    client, so anything at all can arrive at `add`.

    Measured while writing this lane: a `MagicMock` client hands back a
    `MagicMock` for `last_usage`, which is truthy and which Python will
    add to an integer without complaint — producing a "token count" that
    is a mock object all the way onto a stream somebody bills from.
    """

    def _ledger(self):
        from core.runtime.usage import Ledger

        return Ledger()

    def test_a_usage_is_counted(self):
        from core.runtime.backends.base import Usage

        ledger = self._ledger()
        assert ledger.add(Usage(1, 2, 3)) is not None
        assert (ledger.calls, ledger.total) == (1, 3)

    def test_none_is_not(self):
        ledger = self._ledger()
        assert ledger.add(None) is None
        assert ledger.calls == 0

    def test_a_mock_is_not(self):
        from unittest.mock import MagicMock

        ledger = self._ledger()
        assert ledger.add(MagicMock()) is None
        assert (ledger.calls, ledger.prompt) == (0, 0)

    def test_a_dict_that_looks_close_enough_is_not(self):
        ledger = self._ledger()
        assert ledger.add({"prompt_tokens": 5, "completion_tokens": 1}) is None
        assert ledger.calls == 0

    def test_the_per_call_list_is_bounded_and_the_totals_are_not(self):
        from core.runtime.backends.base import Usage
        from core.runtime.usage import Ledger

        ledger = self._ledger()
        for _ in range(Ledger.MAX_PER_CALL + 10):
            ledger.add(Usage(1, 1, 2))
        assert len(ledger.per_call) == Ledger.MAX_PER_CALL
        assert ledger.calls == Ledger.MAX_PER_CALL + 10
        assert ledger.total == (Ledger.MAX_PER_CALL + 10) * 2

    def test_absorbing_another_ledger_goes_through_the_same_arithmetic(self):
        from core.runtime.backends.base import Usage

        one, two = self._ledger(), self._ledger()
        one.add(Usage(10, 1, 11))
        two.add(Usage(20, 2, 22))
        two.add(Usage(30, 3, 33))
        one.absorb(two)
        assert (one.calls, one.prompt, one.total) == (3, 60, 66)

    def test_absorbing_itself_does_not_double_a_run(self):
        from core.runtime.backends.base import Usage

        ledger = self._ledger()
        ledger.add(Usage(10, 1, 11))
        ledger.absorb(ledger)
        assert ledger.calls == 1

    def test_the_console_line_is_empty_when_nothing_was_reported(self):
        assert self._ledger().console_line() == ""

    def test_the_console_line_says_call_in_the_singular(self):
        from core.runtime.backends.base import Usage

        ledger = self._ledger()
        ledger.add(Usage(3, 1, 4))
        assert ledger.console_line().endswith("over 1 call")
