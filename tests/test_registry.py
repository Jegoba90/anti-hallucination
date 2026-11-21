"""server.json, the entry in the official MCP Registry, agrees with the package.

The registry takes server.json as published: a version left behind sends
clients to an old release, and a name the README does not carry fails the
registry's check that the PyPI package is ours. Release by release, these
are the lines that drift.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination import __version__  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
SERVER = json.loads((_ROOT / "server.json").read_text(encoding="utf-8"))
PACKAGE = SERVER["packages"][0]


def test_every_version_is_the_packages() -> None:
    assert SERVER["version"] == __version__
    assert PACKAGE["version"] == __version__
    assert [argument["value"] for argument in PACKAGE["runtimeArguments"]] == [f"antihallucination[mcp]=={__version__}"]


def test_it_launches_the_pypi_package_over_stdio() -> None:
    assert PACKAGE["registryType"] == "pypi"
    assert PACKAGE["identifier"] == "antihallucination"
    assert [argument["value"] for argument in PACKAGE["packageArguments"]] == ["mcp"]
    assert PACKAGE["transport"] == {"type": "stdio"}


def test_the_readme_carries_the_name_the_registry_checks() -> None:
    # The README is the package's description on PyPI; the registry looks for
    # "mcp-name: <name>" there, followed by a space, a tag or the comment's end.
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(r"mcp-name: " + re.escape(SERVER["name"]) + r"(\s|<|-->)", readme)


def test_the_listing_fits_the_registrys_limits() -> None:
    assert re.fullmatch(r"io\.github\.Jegoba90/[a-zA-Z0-9._-]+", SERVER["name"])
    assert 1 <= len(SERVER["description"]) <= 100
    assert 1 <= len(SERVER["title"]) <= 100
