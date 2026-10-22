"""
What the documents say about the code, where a test can say it: the environment variables.

CONTRIBUTING.md has a table of them ("Environment switches") that calls itself the whole list. These tests keep it that: every `PORT_*` and `PENTAMOOR_*` name the
runtime reads (`getenv("NAME")` in src/port) or the launchers and tools read is in the table, each is there once, and every name in the table, and every one the README
and the release README mention, is read by something. No game files are needed.

    python3 -m pytest tools/release/test_docs.py
"""
import os
import re
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
NAME = re.compile(r"(?<![A-Za-z0-9_])((?:PORT|PENTAMOOR)_[A-Z0-9_]+)")
GETENV = re.compile(r'getenv\("((?:PORT|PENTAMOOR)_[A-Z0-9_]+)"\)')
NOT_ENVIRONMENT = {"PORT_IOS"}                      # compile-time macros that look like variables
NOT_ENVIRONMENT_PREFIX = ("PORT_STATIC_", "PENTAMOOR_STATIC_")
LAUNCHERS = ["pentamoor", "pentamoor.bat", "pentamoor-install", "pentamoor-install.bat"]


def tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, stdout=subprocess.PIPE).stdout
    return [p for p in out.decode("utf-8", "surrogateescape").split("\0") if p]


def read(path):
    with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as f:
        return f.read()


def is_variable(name):
    return name not in NOT_ENVIRONMENT and not name.startswith(NOT_ENVIRONMENT_PREFIX)


def read_by_the_runtime():
    names = set()
    for p in tracked():
        if p.startswith("src/") and p.endswith((".c", ".h", ".m")):
            names |= set(GETENV.findall(read(p)))
    return names


def read_by_launchers_and_tools():
    names = set()
    for p in tracked():
        base = os.path.basename(p)
        if base.startswith("test_") or p.endswith(".md"):
            continue
        launcher = p in LAUNCHERS
        installer = p.startswith("tools/install/") and p.endswith(".py")
        ios = p in ("tools/ios/deploy.py", "tools/ios/deploy.sh")
        steamdeck = p.startswith("tools/steamdeck/") and p.endswith((".py", ".sh"))
        if launcher or installer or ios or steamdeck:
            names |= {n for n in NAME.findall(read(p)) if is_variable(n)}
    return names


def table_names():
    """{name: how many rows list it} for the first cell of every row of CONTRIBUTING.md's table of environment variables."""
    text = read("CONTRIBUTING.md")
    section = text.split("## Environment switches", 1)[1].split("\n## ", 1)[0]
    counts = {}
    for line in section.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        first = line.split("|")[1]
        for n in NAME.findall(first):
            counts[n] = counts.get(n, 0) + 1
    return counts


def mentioned_anywhere_in_code(name):
    for p in tracked():
        if p.endswith(".md") or p.startswith("tools/difftest/vectors/"):
            continue
        try:
            if name in read(p):
                return True
        except OSError:
            continue
    return False


def test_the_table_has_every_variable_the_runtime_reads():
    missing = sorted(read_by_the_runtime() - set(table_names()))
    assert not missing, f"read by src/port but not in CONTRIBUTING.md's table: {missing}"


def test_the_table_has_every_variable_the_launchers_and_tools_read():
    missing = sorted(read_by_launchers_and_tools() - set(table_names()))
    assert not missing, f"read by a launcher or a tool but not in CONTRIBUTING.md's table: {missing}"


def test_every_variable_is_in_the_table_once():
    twice = sorted(n for n, k in table_names().items() if k > 1)
    assert not twice, f"listed in more than one row of CONTRIBUTING.md's table: {twice}"


def test_every_variable_in_the_table_is_read_by_something():
    gone = sorted(n for n in table_names() if not mentioned_anywhere_in_code(n))
    assert not gone, f"in CONTRIBUTING.md's table but named by no file of the code: {gone}"


@pytest.mark.parametrize("doc", ["README.md", "tools/release/README.release.txt"])
def test_the_variables_a_player_is_told_about_exist(doc):
    gone = sorted(n for n in set(NAME.findall(read(doc))) if is_variable(n) and n not in (read_by_the_runtime() | read_by_launchers_and_tools()))
    assert not gone, f"{doc} names variables that nothing reads: {gone}"


def test_the_default_screen_is_the_one_the_readme_says():
    """The README says the game runs at 1024x768 unless PORT_RES says otherwise: that is main.c's default."""
    main = read("src/port/main.c")
    assert re.search(r"#define\s+DEFAULT_RES_W\s+1024\b", main) and re.search(r"#define\s+DEFAULT_RES_H\s+768\b", main)
    assert "1024x768" in read("README.md")


# ---- the installer's options for the licence step ------------------------------------------------------------------------------------------------------------------
LICENCE_OPTIONS = ("--no-licence-value", "--keep-cd-check")


def installer_options():
    return set(re.findall(r'add_argument\("(--[a-z0-9-]+)"', read("tools/install/install.py")))


def test_the_licence_options_are_the_installers():
    assert set(LICENCE_OPTIONS) <= installer_options()


@pytest.mark.parametrize("doc", ["README.md", "CONTRIBUTING.md", "tools/release/README.release.txt", "docs/notes/sota-licence.md", "docs/notes/sota-comparison.md"])
def test_the_licence_options_are_documented_where_the_install_is(doc):
    text = read(doc)
    missing = [o for o in LICENCE_OPTIONS if o not in text]
    assert not missing, f"{doc} does not mention the installer's {missing}"


def test_the_docs_name_no_licence_option_the_installer_does_not_have():
    """Every licence option the documents name for the installer exists in install.py (a rename must reach the text). (`--no-cd`, which the 2.15 install replaced with the default and --keep-cd-check, may be named as gone.)"""
    have = installer_options()
    for doc in ("README.md", "tools/release/README.release.txt", "docs/notes/sota-licence.md"):
        named = set(re.findall(r"(?<![A-Za-z0-9-])(--(?:no-(?:licence|licenses?|serial)|keep-cd)[a-z0-9-]*)", read(doc)))
        assert named <= have, f"{doc} names installer options that do not exist: {sorted(named - have)}"
