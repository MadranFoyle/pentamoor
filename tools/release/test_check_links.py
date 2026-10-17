"""Tests for check_links.py, on Markdown files the tests make up, and on the repository's own."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_links  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def make(tmp_path, files):
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(tmp_path)


def test_a_link_to_a_file_that_is_there_is_fine(tmp_path):
    root = make(tmp_path, {"README.md": "see [the guide](docs/guide.md) and ![pic](docs/pic.png)\n", "docs/guide.md": "# Guide\n", "docs/pic.png": "x"})
    assert check_links.check(root) == []


def test_a_link_to_a_file_that_is_not_there_is_reported_with_its_line(tmp_path):
    root = make(tmp_path, {"README.md": "one\n\nsee [the guide](docs/missing.md)\n"})
    problems = check_links.check(root)
    assert len(problems) == 1 and problems[0].startswith("README.md:3:") and "docs/missing.md" in problems[0]


def test_links_are_relative_to_the_file_that_holds_them(tmp_path):
    root = make(tmp_path, {"docs/notes/a.md": "[up](../PHASE.md) [side](b.md) [wrong](PHASE.md)\n", "docs/notes/b.md": "", "docs/PHASE.md": ""})
    problems = check_links.check(root)
    assert len(problems) == 1 and "(PHASE.md)" not in problems[0] and "PHASE.md: no such file" in problems[0] and ":1:" in problems[0]


def test_a_folder_is_a_target_too(tmp_path):
    root = make(tmp_path, {"README.md": "[notes](docs/notes/)\n", "docs/notes/a.md": ""})
    assert check_links.check(root) == []


def test_web_links_are_not_fetched(tmp_path):
    root = make(tmp_path, {"README.md": "[x](https://example.invalid/nothing) [m](mailto:a@example.invalid)\n"})
    assert check_links.check(root) == []


def test_an_anchor_has_to_match_a_heading(tmp_path):
    text = "# Top\n\n## Install and run\n\n### From source (Linux)\n\n## Install and run\n\n[ok](#install-and-run) [again](#install-and-run-1) [src](#from-source-linux) [bad](#nothing-here)\n"
    root = make(tmp_path, {"README.md": text})
    problems = check_links.check(root)
    assert len(problems) == 1 and "#nothing-here" in problems[0]


def test_an_anchor_in_another_file_is_looked_up_there(tmp_path):
    root = make(tmp_path, {"README.md": "[a](docs/x.md#the-part) [b](docs/x.md#no-part)\n", "docs/x.md": "# Title\n\n## The part\n"})
    problems = check_links.check(root)
    assert len(problems) == 1 and "#no-part" in problems[0]


def test_code_is_not_links(tmp_path):
    text = "`[a](nothing.md)` is code\n\n```\n[b](also-nothing.md)\n```\n\n    [c](indented)\n"
    root = make(tmp_path, {"README.md": text})
    assert check_links.check(root) == []


def test_a_reference_definition_is_checked(tmp_path):
    root = make(tmp_path, {"README.md": "[x][ref] and [y][gone]\n\n[ref]: docs/a.md\n[gone]: docs/gone.md\n", "docs/a.md": ""})
    problems = check_links.check(root)
    assert len(problems) == 1 and "gone.md" in problems[0]


def test_a_link_with_a_title_and_a_percent_escape(tmp_path):
    root = make(tmp_path, {"README.md": '[a](docs/a%20b.md "the title")\n', "docs/a b.md": ""})
    assert check_links.check(root) == []


def test_the_repositorys_own_markdown_has_no_broken_link():
    problems = check_links.check(ROOT, check_links.tracked_markdown(ROOT))
    assert problems == [], "\n".join(problems)


def test_the_checker_does_find_the_links_of_the_readme():
    """Guards the guard: if the pattern stopped matching, the test above would pass for the wrong reason."""
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
        links = [t for _, t in check_links.links_of(f.read())]
    assert "CONTRIBUTING.md" in links and any(t.startswith("docs/notes/") for t in links) and "#legal" in links
