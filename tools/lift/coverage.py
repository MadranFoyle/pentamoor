#!/usr/bin/env python3
"""
coverage.py - how much of the lifted handlers the recorded vectors executed.

A vector only proves the instructions it runs. Build the harness with -DLIFT_COVERAGE, run the vectors with FLAT_COV set to
a file (every harness process appends the addresses it executed), then:

    python3 tools/lift/coverage.py sources/generated/lift/handlers_gen.c cov.txt

prints, per handler and in total, how many of the lifted instructions were executed.
"""
import re
import sys


def main():
    gen, cov = sys.argv[1], sys.argv[2]
    hit = {int(l, 16) for l in open(cov) if l.strip()}
    funcs, cur = {}, None
    for line in open(gen):
        m = re.match(r"uint32_t lifted_([0-9a-f]{8})\(", line)
        if m:
            cur = funcs.setdefault(m.group(1), [])
        m = re.search(r"LIFT_COV\(0x([0-9a-f]+)u\)", line)
        if m and cur is not None:
            cur.append(int(m.group(1), 16))
    total = covered = full = never = 0
    worst = []
    for name, insns in sorted(funcs.items()):
        n, c = len(insns), sum(1 for a in insns if a in hit)
        total, covered = total + n, covered + c
        full += c == n
        never += c == 0
        worst.append((c / n if n else 1.0, name, c, n))
    print(f"{len(funcs)} handlers, {total} instructions, {covered} executed ({100.0 * covered / total:.1f}%)")
    print(f"{full} handlers fully executed, {never} never executed at all")
    for frac, name, c, n in sorted(worst)[:10]:
        print(f"   least covered: Handler_{name} {c}/{n}")


if __name__ == "__main__":
    main()
