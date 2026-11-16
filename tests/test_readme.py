"""The README's examples print what their comments say.

A README block that is never run drifts from the code while the suite stays
green. This runs both Python blocks as printed, and the sales-report example
as a user would.
"""

import contextlib
import io
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _blocks() -> list[str]:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)```", readme, re.DOTALL)
    assert len(blocks) == 2, "expected the compose/verify example and the write example"
    return blocks


def _block() -> str:
    return _blocks()[0]


def test_the_readme_example_prints_what_its_comments_say() -> None:
    lines = _block().splitlines()
    promised = [
        following[2:]
        for line, following in zip(lines, lines[1:])
        if line.startswith("print(") and following.startswith("# ")
    ]
    out = io.StringIO()
    sys.path.insert(0, str(_ROOT))
    try:
        with contextlib.redirect_stdout(out):
            exec(_block(), {})
    finally:
        sys.path.remove(str(_ROOT))

    assert promised, "the example no longer says what it prints"
    assert out.getvalue().splitlines() == promised


def test_the_sales_report_example_runs_and_its_receipt_replays() -> None:
    result = subprocess.run(
        [sys.executable, str(_ROOT / "examples" / "sales_report.py")],
        capture_output=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Las ventas fueron 1.250 unidades (-3,2 %)." in result.stdout
    assert "replay:          reproduced" in result.stdout


def test_the_readme_write_example_runs_as_written(monkeypatch) -> None:
    """No key here, so ClaudeWriter is swapped for a stand-in; every other name
    in the block is the real one, so a renamed function or argument fails."""
    sys.path.insert(0, str(_ROOT))
    try:
        import antihallucination.writers as writers

        class StandIn:
            name = "test:stand-in"

            def __call__(self, system: str, prompt: str) -> str:
                assert "1,250" not in prompt and "-3.2" not in prompt
                return "Sales fell {sales_change:abs} to {sales}."

        monkeypatch.setattr(writers, "ClaudeWriter", StandIn)
        out = io.StringIO()
        namespace: dict[str, object] = {}
        with contextlib.redirect_stdout(out):
            exec(_blocks()[0], namespace)
            exec(_blocks()[1], namespace)
    finally:
        sys.path.remove(str(_ROOT))

    assert out.getvalue().splitlines()[-1] == "Sales fell 3.2% to 1,250 units."
