# Where the code in this repository comes from

One place for this, so the comments in the code do not have to carry it.

- **The lifter, the runtime, the installers, the platform work, the tools and the notes** (`tools/`, `src/port`, `docs/`) were written for this project from the game's own executables and by running the game, by its maintainer and with an AI coding assistant.
- **`src/native`** is hand-written C that reimplements some of the original engine's functions. It was written in the project's earlier repository, a fork of [benprew/microprose-shandalar-source](https://github.com/benprew/microprose-shandalar-source),
  whose Ghidra decompilation of the game's programs was the starting point for understanding them. Early on the functions were written with a decompiler's reading of the original in front of the author; later ones from the machine code itself and from recorded runs of the original, and every one was checked against the original running (`tools/difftest`).
  The comments in `src/native` say what each function reimplements and how it was checked; they no longer point at the decompiled material, because that material is not in this repository.
- **The decompiled material is not here.** It was removed in October 2026 and the repository's history starts from a copy of the finished tree (see "History" in the README). `tools/release/check_tree.py` fails CI if anything that looks like decompiler output is tracked.
- **Authorship check, 2026-10-23.** A line-by-line blame of every file in this tree against the earlier repository's history attributes all but 34 lines to the maintainer's accounts. Those 34 lines are blank lines, Markdown code fences and the generic patterns of a `.gitignore`
  (build output, editor swap files), which came with the fork's first commit. Nothing of the fork's author's code or text remains in the tree. (The fork had no license file of its own.)
- **The game itself** (its programs, art, sounds, card data, text) belongs to its owners and is never part of this repository; the project builds from the user's own copy. The license of this repository does not cover it.
