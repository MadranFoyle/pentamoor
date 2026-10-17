#!/usr/bin/env python3
"""
sotacmptable.py - the rows of the function-comparison tables in docs/notes/sota-comparison.md, for any pairs of builds, as Markdown.

    sotacmptable.py LABEL=OLD.EXE:NEW.EXE [LABEL=OLD:NEW ...]

For each pair it runs what sotacmp.py runs (the functions of both programs found with tools/lift/fnscan.py, matched in stages) and prints one row of each of the two tables:
the first counts every function the scan finds, by how well it matches (identical bytes with relocations and outside calls masked, same instruction shape, the Dice score bands),
and the functions that have no counterpart; the second counts only the functions reachable from the entry point and the exports and the bytes that are identical. A path may not
contain ':' (use the same folder layout as sources/). Read-only; prints counts and labels, never code or data.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sotacmp as sc  # noqa: E402


def main(argv):
    pairs = []
    for a in argv[1:]:
        label, _, rest = a.partition("=")
        old, _, new = rest.partition(":")
        if not (label and old and new):
            print(__doc__)
            return 2
        pairs.append((label, old, new))
    rows1, rows2 = [], []
    for label, old_path, new_path in pairs:
        oi, ni = sc.Image(old_path), sc.Image(new_path)
        old, _ = sc.scan_functions(oi)
        new, _ = sc.scan_functions(ni)
        M = sc.match(old, new, lambda s: None)
        r = sc.summarize(label, old, new, M)
        b = r["bands"]
        rows1.append("| %s | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d |" % (label, r["old"], r["new"], b["identical"], b["same shape"], b["0.9-1.0"], b["0.7-0.9"], b["0.5-0.7"],
                                                                                   b["below 0.5"], r["removed"], r["added"]))
        share = 100.0 * r["bytes_old"]["identical"] / max(1, r["bytes_old_total"])
        rows2.append("| %s | %d | %d | %d | %d | %d | %d | %d%% |" % (label, r["old_reachable"], r["new_reachable"], r["removed_reachable"], r["added_reachable"], r["bytes_old"]["identical"],
                                                                      r["bytes_old_total"], round(share)))
    print("| comparison | functions old | functions new | identical | same shape | 0.9-1.0 | 0.7-0.9 | 0.5-0.7 | below 0.5 | old only | new only |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    print("\n".join(rows1))
    print()
    print("| comparison | old reachable | new reachable | old only (reachable) | new only (reachable) | bytes of old functions: identical | all | share identical |")
    print("|---|---|---|---|---|---|---|---|")
    print("\n".join(rows2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
