"""Tests of the pad regression runner's reading of the scripts' output, its table and its exit status, and a syntax check of the controller scripts (no game, no process: the text a script prints is
made up here; the scripts themselves are only compiled).

    python3 -m pytest tools/soak
"""
import io
import os
import py_compile
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pad_regression as pr  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

SAMPLE = """--- newgame
ok    the title menu: 2 targets (Load and Resume are greyed): mode screen, 2
ok    the D-pad reaches 'Start New Game' (1 presses)
DIGEST world 71f80d9b47c4
--- save
FAIL  Save: the ten slots are targets (screen, 6)
ok    the D-pad reaches the first slot (3 presses)
ok    the D-pad reaches the first slot (2 presses)
all checks passed
"""


def test_normalise_drops_what_changes_between_runs():
    a = pr.normalise("the D-pad reaches 'Start New Game' (1 presses)")
    b = pr.normalise("the D-pad reaches 'Resume Game' (3 presses)")
    assert a == b
    assert pr.normalise("the party walked east: (3, 4) -> (5, 6)") == pr.normalise("the party walked east: (7, 4) -> (7, 9)")
    assert pr.normalise("gold 400 -> 385, food 100 -> 110") == "gold -> food ->"


def test_parse_reads_checks_steps_digests_and_the_final_line():
    r = pr.parse_output(SAMPLE, "sota_pad_play.py", 7, 1)
    assert [c[1] for c in r.checks] == [True, True, False, True, True]
    assert r.digests == {"world": "71f80d9b47c4"}
    assert r.final == "all checks passed"
    assert [c[0] for c in r.failed] == [r.checks[2][0]]
    keys = [c[0] for c in r.checks]
    assert keys[0].startswith("sota_pad_play:newgame:") and keys[2].startswith("sota_pad_play:save:")
    assert len(set(keys)) == len(keys)                                  # the same check twice in a run is two rows (#1, #2)


def test_a_check_that_repeats_keeps_its_rows_apart_between_runs():
    a = pr.parse_output(SAMPLE, "s.py", 1, 1)
    b = pr.parse_output(SAMPLE.replace("FAIL  Save", "ok    Save"), "s.py", 1, 2)
    rows = pr.table([a, b])
    save = [k for k in rows if ":save:Save" in k][0]
    assert rows[save] == {(1, "s.py", 1): False, (1, "s.py", 2): True}


def test_render_lists_flaky_and_failing_rows_and_exits_nonzero():
    a = pr.parse_output(SAMPLE, "s.py", 1, 1)
    b = pr.parse_output(SAMPLE.replace("FAIL  Save", "ok    Save"), "s.py", 1, 2)
    out = io.StringIO()
    assert pr.render([a, b], out=out) == 1
    text = out.getvalue()
    assert "FLAKY F." in text and "the ten slots" in text
    assert "0 failed in every run, 1 in some runs only (flaky), 4 ok in every run" in text.replace("check(s) ", "")
    assert text.strip().endswith("FAIL")


def test_render_passes_when_every_check_is_ok_in_every_run():
    good = SAMPLE.replace("FAIL  Save", "ok    Save")
    out = io.StringIO()
    assert pr.render([pr.parse_output(good, "s.py", 1, i) for i in (1, 2, 3)], out=out) == 0
    assert out.getvalue().strip().endswith("PASS")
    assert "FLAKY" not in out.getvalue() and "FAIL" not in out.getvalue()


def test_a_script_that_did_not_finish_is_a_problem_even_with_no_failed_check():
    r = pr.parse_output("--- newgame\nok    a check\n", "s.py", 1, 1)
    r.problem = "no final line"
    out = io.StringIO()
    assert pr.render([r], out=out) == 1
    assert "PROBLEM" in out.getvalue()


def test_two_runs_of_one_seed_that_made_different_worlds_are_reported():
    a = pr.parse_output("DIGEST world aaa\nall checks passed\n", "s.py", 5, 1)
    b = pr.parse_output("DIGEST world bbb\nall checks passed\n", "s.py", 5, 2)
    c = pr.parse_output("DIGEST world bbb\nall checks passed\n", "s.py", 6, 1)       # another seed: another world is right
    assert pr.divergences([a, c]) == []
    d = pr.divergences([a, b])
    assert len(d) == 1 and d[0][1] == 5 and d[0][2] == "world"
    out = io.StringIO()
    assert pr.render([a, b], out=out) == 1 and "DIVERGED" in out.getvalue()


def test_all_prints_the_rows_that_were_always_ok():
    good = SAMPLE.replace("FAIL  Save", "ok    Save")
    short, full = io.StringIO(), io.StringIO()
    pr.render([pr.parse_output(good, "s.py", 1, 1)], out=short)
    pr.render([pr.parse_output(good, "s.py", 1, 1)], show_all=True, out=full)
    assert "title menu" not in short.getvalue() and "title menu" in full.getvalue()


def test_the_pinned_tables_of_the_scripts_are_read_from_their_text():
    seeds = pr.pinned_seeds("sota_pad_play.py")
    assert seeds and all(isinstance(s, int) for s in seeds)


@pytest.mark.parametrize("script", sorted({s for game in pr.GAMES.values() for s, _a in game}) + ["pad_regression.py"])
def test_the_scripts_compile(script, tmp_path):
    """CI has no game: the scripts only have to be valid Python (and name the --seed they are run with)."""
    py_compile.compile(os.path.join(HERE, script), cfile=str(tmp_path / "x.pyc"), doraise=True)
    if script != "pad_regression.py":
        with open(os.path.join(HERE, script), encoding="utf-8") as f:
            assert '"--seed"' in f.read()


def test_the_runner_skips_a_game_that_is_not_installed(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PENTAMOOR_RUN", str(tmp_path / "no-runtime"))
    assert pr.main(["--game", "2.15", "--workdir", str(tmp_path)]) == 2
    assert pr.main(["--game", "both", "--workdir", str(tmp_path)]) == 2
    assert "runtime is not built" in capsys.readouterr().err
