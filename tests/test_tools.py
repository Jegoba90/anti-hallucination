"""The tools a change to the checks is measured with run end to end.

tools/compare_versions.py compares this checkout's decisions with a git ref's
on random inputs; tools/timing.py shows how check time grows with the input.
Run here on a few inputs each, so they do not rot between the changes that
need them.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git") is not None and (ROOT / ".git").exists()


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300
    )


@pytest.mark.skipif(not GIT, reason="needs git and a git checkout")
def test_compare_versions_compares_with_head() -> None:
    done = _run("tools/compare_versions.py", "HEAD", "--documents", "30", "--data", "100")

    # 1 is fine: an uncommitted change may decide differently on purpose.
    assert done.returncode in (0, 1), done.stderr
    assert "documents: 30," in done.stdout
    assert "Traceback" not in done.stderr


@pytest.mark.skipif(not GIT, reason="needs git and a git checkout")
def test_compare_versions_says_when_the_ref_is_not_there() -> None:
    done = _run("tools/compare_versions.py", "no-such-ref-anywhere")

    assert done.returncode == 2
    assert "cannot read" in done.stderr


def test_timing_times_a_shape() -> None:
    done = _run("tools/timing.py", "moves-with-subject", "--start-kb", "4", "--max-kb", "8")

    assert done.returncode == 0, done.stderr
    assert "moves-with-subject           4 KB" in done.stdout


def test_timing_says_when_a_shape_is_refused() -> None:
    # At 16 KB, 273 facts of the value each of 2,730 figures has: past MAX_MATCHES.
    done = _run("tools/timing.py", "same-value", "--start-kb", "16", "--max-kb", "16")

    assert done.returncode == 0, done.stderr
    assert "refused" in done.stdout
