#!/usr/bin/env python3
"""
progress.py - turn the installer's text output into a percentage and a few words, for a progress bar.

    pentamoor-install --yes disc.iso 2>&1 | python3 tools/steamdeck/progress.py [--log FILE]

Reads the installer's output on stdin (it is the installer's own text, so this has to follow it: test_steamdeck.py runs a real install log through it) and writes one line
per change to stdout:   PERCENT|what is being done          for example   31|Copying the game files (400 of 967)
Every input line is also appended to --log if given, so nothing the installer said is lost. The percentage never goes down and ends at 100 on "built.".

The stages and where they sit (a typical install: reading the disc 1 min, translating 40 s, compiling 1 to 10 minutes):
    reading the disc 2-18, the media 19-20, the compiler (a download of about 100 MB when there is none, with its own percentage) 22-32, translating to C 33-42,
    compiling 43-93 (the installer prints the share of the C compiled), linking 94-96, checking each game module loads 97-99, built 100.
Spells of the Ancients 2.15 added to an installed game (pentamoor-install --sota DISC --patch FILE, with no first disc) starts with other steps, found by the installer's own lines
("expansion disc:" and "Spells of the Ancients 2.15 into"): the two files checked 1-4, the folder made from the first game's files 4-10, the expansion's cabinet unpacked 10-18, the
patch 19, the programs checked 21; the rest (compiler, translating, compiling, linking) is the same as above, then the licence step 98, built 100.
"""
import re
import sys

STAGES = [
    (re.compile(r"^expansion disc: "), 1, "Checking the Spells of the Ancients disc image"),
    (re.compile(r"^patch: "), 3, "Checking the 2.15 patch"),
    (re.compile(r"^Spells of the Ancients 2\.15 into "), 4, "Making the Spells of the Ancients folder"),
    (re.compile(r"^reading Setup/data1\.cab"), 10, "Reading the expansion's files"),
    (re.compile(r"^2\.15 patch: "), 19, "Applying the 2.15 patch"),
    (re.compile(r"^disc: "), 1, "Reading the disc image"),
    (re.compile(r"^reading Setup/data\.z"), 2, "Reading the disc image"),
    (re.compile(r"^game files:"), 18, "Game files copied"),
    (re.compile(r"^sound from the disc"), 19, "Copying the music"),
    (re.compile(r"^statwin from the disc"), 20, "Copying the movies"),
    (re.compile(r"^programs:"), 21, "Checking the game's programs"),
    (re.compile(r"^downloading Zig"), 22, "Downloading the C compiler (about 100 MB)"),
    (re.compile(r"^unpacking Zig"), 31, "Unpacking the C compiler"),
    (re.compile(r"^compiler: "), 32, "Found a C compiler"),
    (re.compile(r"^lifting the game"), 33, "Translating the game to C"),
    (re.compile(r"^lifting Spells of the Ancients"), 38, "Translating Spells of the Ancients to C"),
    (re.compile(r"^lifted |  \[\w+\] already lifted"), 42, "Translating the game to C"),
    (re.compile(r"^compiling \d+ files"), 43, "Compiling the game"),
    (re.compile(r"^all objects are up to date"), 93, "Compiling the game"),
    (re.compile(r"^linking game_"), 94, "Linking the game"),
    (re.compile(r"^  game_\w+: loads in the runtime"), 97, "Checking the game starts"),
    (re.compile(r"^licence: "), 98, "Writing the licence value"),
    (re.compile(r"^removed "), 99, "Removing the intermediate files"),
    (re.compile(r"^built\."), 100, "Done"),
]
FILES = re.compile(r"^\s+(\d+)/(\d+) files")
COMPILE = re.compile(r"^\s+\[(\d+)/(\d+)\]\s+(\d+)%")
ZIGPCT = re.compile(r"^\s+(\d+)%\s*$")
LIFTED = re.compile(r"^\s+\[\w+\] done in ")


class Progress:
    """Feed lines; each feed returns (percent, text) when either changed, else None."""

    def __init__(self):
        self.pct = 0
        self.text = ""
        self.zig = False
        self.lift_done = 0
        self.expect_sota = False
        self.sota = False                      # in the Spells of the Ancients folder step: "n/m files" lines are its two copies, not the first game's
        self.cab = False                       # ... and the second of them is the expansion's cabinet

    def _set(self, pct, text):
        pct = max(self.pct, min(100, int(pct)))
        if pct == self.pct and text == self.text:
            return None
        self.pct, self.text = pct, text
        return (pct, text)

    def feed(self, line):
        line = line.rstrip("\r\n")
        m = FILES.match(line)
        if m:
            n, total = int(m.group(1)), max(int(m.group(2)), 1)
            if self.sota and self.cab:
                return self._set(10 + 8 * min(n, total) / total, f"Unpacking the expansion's files ({n} of {total})")
            if self.sota:
                return self._set(4 + 6 * min(n, total) / total, f"Copying the first game's files ({n} of {total})")
            return self._set(2 + 16 * min(n, total) / total, f"Copying the game files ({n} of {total})")
        m = COMPILE.match(line)
        if m:
            n, total, share = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return self._set(43 + 50 * share / 100, f"Compiling the game ({n} of {total} files)")
        if self.zig:
            m = ZIGPCT.match(line)
            if m:
                return self._set(22 + 8 * int(m.group(1)) / 100, f"Downloading the C compiler ({m.group(1)}%)")
        if LIFTED.match(line):
            self.lift_done += 1
            return self._set(33 + min(self.lift_done, 9), "Translating the game to C")
        if line.startswith("expansion disc: "):
            self.expect_sota = True
        elif line.startswith("programs: ") and self.expect_sota and not self.sota:
            return None                        # the first game's programs, checked before the Spells of the Ancients folder is made: not the stage this is
        if line.startswith("Spells of the Ancients 2.15 into "):
            self.sota, self.cab = True, False
        elif self.sota and line.startswith("reading Setup/data1.cab"):
            self.cab = True
        if self.sota and re.match(r"^(sound|statwin) from the disc", line):
            return None                        # the expansion run says these are there already (the first game copied them): not a stage of its own
        for pattern, pct, text in STAGES:
            if pattern.search(line):
                self.zig = line.startswith("downloading Zig")
                return self._set(pct, text)
        return None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    log = open(argv[argv.index("--log") + 1], "a") if "--log" in argv else None
    p = Progress()
    out = sys.stdout
    for line in iter(sys.stdin.readline, ""):
        if log:
            log.write(line)
            log.flush()
        r = p.feed(line)
        if r:
            out.write(f"{r[0]}|{r[1]}\n")
            out.flush()
    if log:
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
