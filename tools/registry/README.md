# Verified-name registry

`docs/SYMBOL_VERIFICATION.md` records, in prose and tables, which names were checked against the running
game. This folder turns its tables into a registry and checks the repository against it. Standard
library only; nothing here renames anything.

```bash
python3 tools/registry/build_registry.py   # doc -> verified_names.csv + parse_report.md
python3 tools/registry/check_registry.py   # exit 1 if the registry is inconsistent or an address is not where the executable has it
python3 -m pytest tools/registry           # needs pytest
```

| File | What |
|---|---|
| `verified_names.csv` | `program` (MAGIC/DUEL), `address`, `name`, `kind` (function/global), `evidence`, `section` (the doc heading), `notes` (old names, confidence, where the evidence grade came from) |
| `parse_report.md` | tables with no names (skipped) and rows that could not be read |

## How the doc is read

Every table with an address column and a new-name column (`Now`, `New name`, or `Called` written as
`old -> new`) is a name table; the other seven tables (step codes, traces, bit meanings) are skipped
and listed in `parse_report.md`. A `MAGIC.EXE / DUEL.EXE` address cell gives one row per program
(`none` means no twin). A cell like `0x681eb0` (`0x006a4a08`) under "`DUEL.EXE` addresses; the
MAGIC.EXE global ... in brackets" gives a DUEL row and a MAGIC row. Otherwise the program comes from the
paragraph right above the table, or the nearest heading that names one program.

`evidence` is the strongest grade the row states: `natural`, `synthetic` (the doc's "injected" is
counted as synthetic), `static`, or `qemu` for the live runs on the original game under QEMU (the doc's
"verified, live" before the in-process emulator section). A few rows are upgraded from prose, each
quoting its sentence in `registry.py` (`EVIDENCE_OVERRIDES`), for example "The step runner and
`g_CurrentStepCode` are **verified live**". The `notes` column says where each grade came from.

## Checks

`check_registry.py` always checks that no address is registered twice for a program and that every row has a program, a kind and a name. With the game installed
(`sources/installed/Magic/Program`, or `$PENTAMOOR_GAME`) it also checks every function row against the executable: the address must be a function start that
`tools/lift/fnscan.py` finds in `MAGIC.EXE` or `DUEL.EXE`, and every global row an address in a data section. `build_registry.py --check` (run by `test_registry.py`) checks that
`verified_names.csv` and `parse_report.md` are what the doc says. (The registry used to be checked against the upstream project's decompiled tree, `<program>/function_index.csv` and its symbol maps, which
are no longer in the repository; the checks against the real executables replace that.)

The two table rows that cannot be read give the DUEL twin as "(twin shares a name)" (`SpellChain_InsertEntry`
and `SpellChain_RebuildEntryTargets`). The doc's prose says the two DUEL twins share
`Palette_Subsystem_0049608e`, and a twin table (made by a tool that has since been removed) paired them with `0x004a1bf7` and `0x004a1f15`,
but neither is written in the table, so they are not registered.
