#!/usr/bin/env python3
"""pad_regression.py: the regression check for playing with the controller, in one command, repeatable.

    python3 tools/soak/pad_regression.py [--game 2.15|1.0|both] [--seeds 1,2,3] [--repeat N] [--workdir DIR] [--only STEP,STEP] [--all]

It runs the controller scripts of tools/soak (2.15: sota_pad_play.py; 1.0: pad_play.py, screen_nav_play.py and nav_play.py) once for every seed and every repeat, each with PORT_SEED set
(src/port/seed.h: the same seed gives the same world, shops and decks, so the same script plays the same game), reads the "ok" and "FAIL" lines they print, and prints one table with a row for
each check that was not "ok" in every run, a column for each run ("." ok, "F" failed, "-" not run that time), and a final line. The exit status is 1 if any check failed in any run, if a script did
not finish, or if two runs with the same seed made different worlds (the scripts print DIGEST lines for that: the world, the shop, the opening hand). --all prints every check, not only those.

Nothing is built and nothing is installed: it takes the runtime, the modules and the game folders from where `./pentamoor` and the soak scripts look (src/port/build, sources/installed and
sources/installed_sota/Magic/Program, or $PENTAMOOR_RUN, $PENTAMOOR_MODULE, $PENTAMOOR_GAME, $PENTAMOOR_SOTA). A game whose files are not there is skipped with a line that says so when --game is
both, and is an error when it was asked for by name. The seeds are the scripts' own pinned lists (each script's PINNED table says what is special about each); --seeds overrides them.

NOT for CI: it needs the game. CI runs the unit tests of this file's parsing and table (test_pad_regression.py) and a syntax check of the scripts.
"""
import argparse
import os
import re
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

# the scripts of each game: (file, extra arguments), run once for every seed
GAMES = {
    "2.15": [("sota_pad_play.py", [])],
    "1.0": [("pad_play.py", []), ("screen_nav_play.py", []), ("nav_play.py", [])],
}
TIMEOUT_S = {"sota_pad_play.py": 3600, "pad_play.py": 900, "screen_nav_play.py": 1800, "nav_play.py": 1800}

LINE = re.compile(r"^(ok  |FAIL)  (.*)$")
STEP = re.compile(r"^--- (.*)$")
DIGEST = re.compile(r"^DIGEST (\S+) (.*)$")
FINAL = re.compile(r"^(all checks passed|\d+ (?:check\(s\) )?failed)")


def normalise(text):
    """A check's text without what changes from run to run (numbers, the quoted names, the bracketed details), so the same check is the same row in every run."""
    t = re.sub(r"\([^()]*\)", "", text)
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = re.sub(r"'[^']*'", "''", t)
    t = re.sub(r"\d+", "", t)
    t = re.sub(r"[\s:,.]+", " ", t).strip()
    return t[:100]


class Result:
    """What one run of one script printed."""

    def __init__(self, script, seed, run):
        self.script, self.seed, self.run = script, seed, run
        self.checks = []                    # [(key, ok, text)]
        self.digests = {}
        self.final = None
        self.exit = None
        self.seconds = 0.0
        self.problem = None                 # "timeout", "no final line", ...

    @property
    def failed(self):
        return [c for c in self.checks if not c[1]]


def parse_output(text, script="", seed=None, run=0):
    """The result of a script's output."""
    r = Result(script, seed, run)
    step, seen = "", {}
    for line in text.splitlines():
        m = STEP.match(line)
        if m:
            step = m.group(1).split()[0] if m.group(1) else ""
            continue
        m = DIGEST.match(line)
        if m:
            r.digests[m.group(1)] = m.group(2).strip()
            continue
        m = LINE.match(line)
        if m:
            base = "%s:%s:%s" % (script.replace(".py", ""), step, normalise(m.group(2)))
            seen[base] = seen.get(base, 0) + 1
            r.checks.append(("%s#%d" % (base, seen[base]), m.group(1) == "ok  ", m.group(2)))
            continue
        m = FINAL.match(line)
        if m:
            r.final = m.group(1)
    return r


def table(results):
    """{key: {(seed, run): ok}} over results (the order of the keys: first seen); keys a run did not print are absent for it."""
    rows = {}
    for r in results:
        for key, ok, _text in r.checks:
            rows.setdefault(key, {})[(r.seed, r.script, r.run)] = ok
    return rows


def divergences(results):
    """The digests that differ between runs of the same script and seed: [(script, seed, name, {value: [runs]})]."""
    by = {}
    for r in results:
        for name, v in r.digests.items():
            by.setdefault((r.script, r.seed, name), {}).setdefault(v, []).append(r.run)
    return [(s, sd, n, vals) for (s, sd, n), vals in by.items() if len(vals) > 1]


def render(results, show_all=False, out=sys.stdout):
    """Print the table and the final line; returns the exit status."""
    cols = sorted({(r.seed, r.script, r.run) for r in results}, key=lambda c: (str(c[1]), str(c[0]), c[2]))
    rows = table(results)
    shown = {k: v for k, v in rows.items() if show_all or not all(v.values())}
    clean = sum(1 for v in rows.values() if v and all(v.values()))
    print("", file=out)
    if cols:
        print("columns, in this order: " + "  ".join("%s/seed %s/run %d" % (c[1].replace(".py", ""), c[0], c[2]) for c in cols), file=out)
    flaky = failing = 0
    for key, v in shown.items():
        cells = "".join("." if v.get(c) else ("F" if c in v else "-") for c in cols)
        fails = sum(1 for x in v.values() if not x)
        tag = "ok" if not fails else ("FLAKY" if fails < len(v) else "FAIL")
        flaky += tag == "FLAKY"
        failing += tag == "FAIL"
        print("%-5s %s  %s" % (tag, cells, key), file=out)
    problems = [r for r in results if r.problem]
    for r in problems:
        print("PROBLEM %s seed %s run %d: %s" % (r.script, r.seed, r.run, r.problem), file=out)
    div = divergences(results)
    for script, seed, name, vals in div:
        print("DIVERGED %s seed %s %s: %s" % (script, seed, name, "; ".join("%s in run(s) %s" % (v, ",".join(map(str, rs))) for v, rs in vals.items())), file=out)
    total = sum(len(r.checks) for r in results)
    bad = sum(len(r.failed) for r in results)
    status = 1 if (bad or problems or div) else 0
    print("pad_regression: %d script run(s), %d checks, %d failed; %d check(s) failed in every run, %d in some runs only (flaky), %d ok in every run; %d problem(s), %d diverged digest(s): %s"
          % (len(results), total, bad, failing, flaky, clean, len(problems), len(div), "FAIL" if status else "PASS"), file=out)
    return status


# ---- running ----------------------------------------------------------------------------------------------------------------------------------------------------
def pinned_seeds(script):
    """The script's PINNED table, read from its text (not imported: importing a script starts nothing, but it pulls in the whole soak toolkit)."""
    with open(os.path.join(HERE, script), encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^PINNED\s*=\s*\{(.*?)^\}", text, re.S | re.M)
    if not m:
        return []
    return [int(x) for x in re.findall(r"^\s*(\d+)\s*:", m.group(1), re.M)]


def game_ready(game):
    """(ok, why not): are the files this game's scripts need there?"""
    run = os.environ.get("PENTAMOOR_RUN") or os.path.join(REPO, "src/port/build/pentamoor-run")
    ext = "dylib" if sys.platform == "darwin" else ("dll" if sys.platform.startswith(("win", "msys", "cygwin")) else "so")
    if not os.path.exists(run):
        return False, "the runtime is not built (%s)" % run
    if game == "2.15":
        folder = os.environ.get("PENTAMOOR_SOTA") or os.path.join(REPO, "sources/installed_sota/Magic/Program")
        exe, module = os.path.join(folder, "shandalar.exe"), os.path.join(os.path.dirname(run), "game_shandalar." + ext)
    else:
        folder = os.environ.get("PENTAMOOR_GAME") or os.path.join(REPO, "sources/installed/Magic/Program")
        exe, module = os.path.join(folder, "MAGIC.EXE"), os.path.join(os.path.dirname(run), "game_magic." + ext)
        if not os.path.isdir(os.path.join(REPO, "sources/emu_overlay")):
            return False, "the saved game for the 1.0 duels is missing (sources/emu_overlay)"
    if not os.path.exists(exe):
        return False, "the game is not installed (%s)" % exe
    if not os.path.exists(module) and not os.environ.get("PENTAMOOR_MODULE"):
        return False, "the game module is not built (%s)" % module
    return True, ""


def run_script(script, args, seed, run, workdir, only=None, log=None):
    """One run of one script with PORT_SEED=seed; returns a Result."""
    wd = os.path.join(workdir, "%s_seed%s_run%d" % (script.replace(".py", ""), seed, run))
    os.makedirs(wd, exist_ok=True)
    cmd = [sys.executable, os.path.join(HERE, script), "--workdir", wd, "--seed", str(seed)] + list(args)
    if only and script == "sota_pad_play.py":
        cmd += ["--only", only]
    env = dict(os.environ, PORT_SEED=str(seed), PYTHONUNBUFFERED="1")
    t0 = time.time()
    out_path = os.path.join(wd, "output.txt")
    with open(out_path, "w") as f:
        p = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        problem = None
        try:
            p.wait(TIMEOUT_S.get(script, 1800))
        except subprocess.TimeoutExpired:
            problem = "timeout after %d s" % TIMEOUT_S.get(script, 1800)
            for sig, wait in ((signal.SIGINT, 30), (signal.SIGTERM, 10)):      # SIGINT first: the script's `finally` stops the game it started
                try:
                    os.kill(p.pid, sig)
                except OSError:
                    break
                try:
                    p.wait(wait)
                    break
                except subprocess.TimeoutExpired:
                    pass
            if p.poll() is None:
                p.kill()
                p.wait()
    with open(out_path, errors="replace") as f:
        text = f.read()
    r = parse_output(text, script, seed, run)
    r.exit, r.seconds = p.returncode, time.time() - t0
    if problem:
        r.problem = problem
    elif r.final is None:
        r.problem = "no final line (exit status %s): the script did not finish; see %s" % (p.returncode, out_path)
    if log:
        print("  %s seed %s run %d: %d checks, %d failed, %.0f s%s" % (script, seed, run, len(r.checks), len(r.failed), r.seconds, (", " + r.problem) if r.problem else ""), file=log, flush=True)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", choices=["2.15", "1.0", "both"], default="both")
    ap.add_argument("--seeds", help="comma separated; default: each script's PINNED list")
    ap.add_argument("--repeat", type=int, default=1, help="runs of every script and seed (default 1)")
    ap.add_argument("--workdir", default="/tmp/pad_regression")
    ap.add_argument("--only", help="2.15 only: sota_pad_play.py's --only (newgame,map,save,village,places,duel,reward,back)")
    ap.add_argument("--all", action="store_true", help="print every check, not only those that were not ok in every run")
    ap.add_argument("--scripts", help="comma separated script names to run (default: all of the game's)")
    a = ap.parse_args(argv)
    games = ["2.15", "1.0"] if a.game == "both" else [a.game]
    results, ran = [], 0
    for game in games:
        ok, why = game_ready(game)
        if not ok:
            print("%s: %s" % (("skipped " + game) if a.game == "both" else ("cannot run " + game), why), file=sys.stderr)
            if a.game != "both":
                return 2
            continue
        for script, args in GAMES[game]:
            if a.scripts and script not in a.scripts.split(","):
                continue
            seeds = [int(x) for x in a.seeds.split(",")] if a.seeds else pinned_seeds(script) or [1]
            print("== %s (%s): seeds %s, %d run(s) each" % (script, game, seeds, a.repeat), flush=True)
            for seed in seeds:
                for run in range(1, a.repeat + 1):
                    results.append(run_script(script, args, seed, run, a.workdir, a.only, sys.stdout))
                    ran += 1
    if not ran:
        print("pad_regression: nothing to run (no game is installed)", file=sys.stderr)
        return 2
    return render(results, a.all)


if __name__ == "__main__":
    sys.exit(main())
