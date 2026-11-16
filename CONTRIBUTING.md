# Contributing

Help make data-backed writing easier to inspect and trust. Bug reports,
documentation fixes, and small, focused pull requests are welcome.

## Set up locally

Use Python 3.11 or newer:

```bash
git clone https://github.com/Jegoba90/anti-hallucination.git
cd anti-hallucination
python -m venv .venv
```

Activate the environment with `source .venv/bin/activate` on macOS/Linux or
`.venv\Scripts\Activate.ps1` in PowerShell, then install the development extras:

```bash
python -m pip install -e ".[dev]"
```

The development extras include the test tools, Claude SDK, and MCP SDK. The
test suite uses fixtures and stand-ins; it does not need an API key.

## Make a change

1. Create a branch and keep the change focused on one problem.
2. Add a regression test for a bug fix or a test for new behavior.
3. Update examples or documentation when public behavior changes.
4. Run the same checks as CI:

   ```bash
   pytest tests/ -v
   mypy .
   ruff check .
   ```

For number parsing, language rules, or sentence checks, include examples that
should pass and examples that should fail. Cover Spanish and English where the
rule applies to both. Keep calculations and verdicts in code and facts; do not
add model calls to the checks.

Use synthetic data in tests and issues. Never include API keys, credentials,
private reports, or customer data. Any live-model experiment should remain
separate from the offline test suite.

## Open an issue or pull request

[Open an issue](https://github.com/Jegoba90/anti-hallucination/issues/new/choose)
with a minimal example, expected result, and actual result. Include the package
and Python versions for bugs.

For a new feature, public API change, dependency, or broader redesign, open an
issue first to discuss the scope. Small fixes can go straight to a pull
request. Describe the problem, the resulting behavior, and the checks you ran.

Contributions are covered by the project's [MIT license](LICENSE).
