"""Keep the human release ledger ordered without dropping older releases."""
from pathlib import Path
import re


def test_release_history_is_unique_and_newest_first():
    root = Path(__file__).resolve().parents[1]
    history = (root / 'README.md').read_text().split('### Release history', 1)[1]
    versions = [tuple(map(int, match)) for match in re.findall(
        r'^\| (?:\[)?(\d+)\.(\d+)\.(\d+)(?:\]\([^)]*\))? \|', history, re.M)]
    current = re.search(r'^VERSION = "(\d+)\.(\d+)\.(\d+)"',
                        (root / 'setup.py').read_text(), re.M)
    assert current is not None
    assert versions and versions[0] == tuple(map(int, current.groups()))
    assert len(versions) == len(set(versions))
    assert versions == sorted(versions, reverse=True)
