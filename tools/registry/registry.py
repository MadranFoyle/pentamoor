"""Shared code for the verified-name registry (standard library only).

The registry is built from the tables in docs/SYMBOL_VERIFICATION.md: every table that assigns a name
to an address becomes rows of tools/registry/verified_names.csv. Tables that only record observations
(step codes, traces, bit meanings) are skipped and reported, as is any cell that cannot be read.
"""

import csv
import os
import re

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
DOC = os.path.join(REPO, "docs", "SYMBOL_VERIFICATION.md")
REGISTRY_CSV = os.path.join(HERE, "verified_names.csv")
FIELDS = ["program", "address", "name", "kind", "evidence", "section", "notes"]
PROGRAMS = ("MAGIC", "DUEL")

# Evidence grades, strongest first. "qemu" is the original game running under the QEMU oracle
# (docs/ORACLE_VM.md); "natural" is the in-process emulator in ordinary play; "synthetic" is the real
# function run on an injected input (the doc also calls this "injected"); "static" is code reading.
EVIDENCE_ORDER = ["qemu", "natural", "synthetic", "static"]

# The doc's first live runs used QEMU; everything from this heading on used the in-process emulator.
EMULATOR_HEADING = "Live results from the in-process emulator"

# Evidence the tables do not carry but the surrounding prose states, keyed by (program, address).
# Each entry quotes the sentence it rests on.
EVIDENCE_OVERRIDES = {
    ("MAGIC", 0x0047624F): ("qemu", "The step runner and `g_CurrentStepCode` are **verified live**"),
    ("MAGIC", 0x006FF4C0): ("qemu", "The step runner and `g_CurrentStepCode` are **verified live**"),
    ("MAGIC", 0x004744DE): ("qemu", "The pop ran 98 times and always restored `g_CardEventResult` to 0"),
    ("MAGIC", 0x004751D7): ("qemu", "Push and resolve were watched once on the live game"),
    ("MAGIC", 0x004756A1): ("qemu", "Push and resolve were watched once on the live game"),
    ("MAGIC", 0x00474D1E): ("qemu", "`Magic_ClearSpellStack` is entered once at the start of every turn ... "
                                    "Its name is confirmed."),
    ("MAGIC", 0x00475BB0): ("qemu", "`Magic_DropTopSpell` was entered from `0x004717b4` ... "
                                    "Its name is confirmed."),
}

ADDR_RE = re.compile(r"`0x([0-9a-fA-F]{5,8})`")
TICK_RE = re.compile(r"`([^`]*)`")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\*?")
HEADING_RE = re.compile(r"^(#+)\s+(.*)$")


def fmt_addr(a):
    return f"0x{a:08x}"


def split_row(line):
    """Split a Markdown table row on | outside backticks."""
    cells, cur, in_tick = [], [], False
    for ch in line.strip().strip("|"):
        if ch == "`":
            in_tick = not in_tick
        if ch == "|" and not in_tick:
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    cells.append("".join(cur).strip())
    return cells


def idents(cell):
    """Backticked identifiers in a cell, with any parameter list dropped."""
    out = []
    for t in TICK_RE.findall(cell):
        m = IDENT_RE.match(t.strip())
        if m:
            out.append(m.group(0))
    return out


# --------------------------------------------------------------------------------------------------
# Reading the doc


class Table:
    def __init__(self, line, header, rows, section, headings, before, prev_table):
        self.line = line              # 1-based line of the header row
        self.header = header
        self.rows = rows              # list of (line, cells)
        self.section = section        # nearest heading
        self.headings = headings      # heading chain, outermost first
        self.before = before          # text of the paragraph right above the table
        self.prev_table = prev_table  # the table right above, if nothing but a blank line separates them
        self.program = None           # set while parsing


def read_doc(path=DOC):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    tables, prose = [], []
    chain = []
    i = 0
    last_table, last_table_end = None, -10
    while i < len(lines):
        line = lines[i]
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            chain = [h for h in chain if h[0] < level] + [(level, m.group(2).strip(), i + 1)]
            i += 1
            continue
        if line.startswith("|"):
            start = i
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append((i + 1, split_row(lines[i])))
                i += 1
            header = block[0][1]
            body = [(n, c) for n, c in block[1:] if not all(re.fullmatch(r":?-+:?", x) for x in c)]
            j = start - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            para = []
            while j >= 0 and lines[j].strip() and not lines[j].startswith("|") \
                    and not HEADING_RE.match(lines[j]):
                para.insert(0, lines[j])
                j -= 1
            prev = last_table if not para and j + 1 == last_table_end else None
            t = Table(start + 1, header, body, chain[-1][1] if chain else "",
                      [h[1] for h in chain], " ".join(para), prev)
            tables.append(t)
            last_table, last_table_end = t, i
            continue
        if line.strip():
            prose.append((i + 1, line, chain[-1][1] if chain else ""))
        i += 1
    return tables, prose


def mentions(text):
    return [p for p in PROGRAMS if f"{p}.EXE" in text]


def table_program(t):
    """Which program the single-address rows of a table belong to, and why."""
    if t.prev_table is not None and t.prev_table.program:
        return t.prev_table.program, "same as the table above"
    m = mentions(t.before)
    if len(m) == 1:
        return m[0], "the paragraph above the table"
    for h in reversed(t.headings):
        m = mentions(h)
        if len(m) == 1:
            return m[0], f"heading '{h}'"
    return None, "no program named above the table"


def column(header, *names):
    for i, h in enumerate(header):
        if any(h.lower() == n.lower() for n in names):
            return i
    return None


def classify_evidence(text, before, section, emulator):
    t = text.lower()
    if "natural" in t:
        return "natural", "cell"
    if "synthetic" in t or "injected" in t:
        return "synthetic", "cell"
    if "live" in t and not emulator:
        return "qemu", "cell"
    if re.search(r"\bstatic\b", t):
        return "static", "cell"
    if "static evidence only" in before:
        return "static", "the paragraph above the table"
    if not emulator and re.search(r"verified", section, re.I):
        return "qemu", "the section heading"
    if emulator:
        return "natural", "an emulator section; the row names no grade"
    return "static", "default; no live observation stated for the row"


def parse_doc(path=DOC):
    """Return (rows, problems, skipped_tables). rows are dicts with FIELDS plus 'old_names'."""
    tables, _ = read_doc(path)
    emu_line = None
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if HEADING_RE.match(line) and EMULATOR_HEADING in line:
                emu_line = n
                break
    rows, problems, skipped = [], [], []

    for t in tables:
        hdr = t.header
        dual = column(hdr, "MAGIC.EXE / DUEL.EXE")
        addr_col = dual if dual is not None else column(hdr, "Address")
        new_col = column(hdr, "Now", "New name")
        called_col = column(hdr, "Called")
        old_col = column(hdr, "Was", "Old name", "Old MAGIC name")
        if addr_col is None or (new_col is None and called_col is None):
            skipped.append(t)
            continue
        emulator = emu_line is not None and t.line > emu_line
        single_prog, why = table_program(t)
        t.program = single_prog
        bracket_primary = None
        if dual is None and re.search(r"`?(MAGIC|DUEL)\.EXE`? addresses", t.before):
            bracket_primary = re.search(r"`?(MAGIC|DUEL)\.EXE`? addresses", t.before).group(1)
        name_cols = {addr_col, new_col, called_col, old_col}
        for line_no, cells in t.rows:
            cells = cells + [""] * (len(hdr) - len(cells))
            where = f"line {line_no} ({t.section})"
            # New name and old names.
            if new_col is not None:
                cell = cells[new_col]
                new = idents(cell)
                old = idents(cells[old_col]) if old_col is not None else []
                if not new and "unchanged" in cell.lower() and old:
                    new, note_new = [old[0]], "name unchanged"
                else:
                    note_new = ""
            else:
                cell = cells[called_col]
                if "->" not in cell:
                    problems.append(f"{where}: no `old -> new` in the Called cell: {cell}")
                    continue
                left, right = cell.split("->", 1)
                new, old, note_new = idents(right), idents(left), ""
            if not new:
                problems.append(f"{where}: no name in the new-name cell: {cell}")
                continue
            name = new[0]
            other = " ".join(cells[i] for i in range(len(cells)) if i not in name_cols)
            evidence, ev_src = classify_evidence(other + " " + cell, t.before, t.section, emulator)
            confidence = re.findall(r"\((medium(?:-high)?|high|low)\)", other)
            # Addresses, one per program.
            addr_cell = cells[addr_col]
            targets = []   # (program, address, old names for that program)
            if dual is not None:
                if "/" not in addr_cell:
                    problems.append(f"{where}: expected `MAGIC / DUEL` addresses: {addr_cell}")
                    continue
                parts = addr_cell.split("/", 1)
                for prog, part, prog_old in (("MAGIC", parts[0], old),
                                             ("DUEL", parts[1], [] if "MAGIC" in hdr[old_col] else old)):
                    a = ADDR_RE.search(part)
                    if a:
                        targets.append((prog, int(a.group(1), 16), prog_old))
                    elif part.strip().lower() == "none":
                        pass   # no twin in that program; nothing to register
                    else:
                        problems.append(f"{where}: {prog} address not given ({part.strip()}) for `{name}`")
            else:
                found = ADDR_RE.findall(addr_cell)
                if not found:
                    problems.append(f"{where}: no address in: {addr_cell}")
                    continue
                if len(found) == 2 and bracket_primary:
                    other_prog = "MAGIC" if bracket_primary == "DUEL" else "DUEL"
                    old_main = idents(cells[old_col].split("(")[0]) if old_col is not None else []
                    old_br = idents(cells[old_col].split("(", 1)[1]) if old_col is not None \
                        and "(" in cells[old_col] else []
                    targets.append((bracket_primary, int(found[0], 16), old_main))
                    targets.append((other_prog, int(found[1], 16), old_br))
                elif len(found) == 1:
                    prog = bracket_primary or single_prog
                    if prog is None:
                        problems.append(f"{where}: cannot tell which program `{name}` belongs to ({why})")
                        continue
                    targets.append((prog, int(found[0], 16), old))
                else:
                    problems.append(f"{where}: {len(found)} addresses, cannot pair them: {addr_cell}")
                    continue
            for prog, addr, prog_old in targets:
                ev, src = evidence, ev_src
                notes = []
                ov = EVIDENCE_OVERRIDES.get((prog, addr))
                if ov and EVIDENCE_ORDER.index(ov[0]) < EVIDENCE_ORDER.index(ev):
                    ev, src = ov[0], f'prose: "{ov[1]}"'
                if src != "cell":
                    notes.append(f"evidence: {src}")
                if note_new:
                    notes.append(note_new)
                if confidence:
                    notes.append("confidence " + "/".join(confidence))
                olds = [o for o in prog_old if o != name]
                if olds:
                    notes.append("was " + ", ".join(olds))
                if any(o.endswith("*") for o in olds):
                    notes.append("old name given as a pattern")
                rows.append({
                    "program": prog, "address": addr, "name": name, "kind": "", "evidence": ev,
                    "section": t.section, "notes": "; ".join(notes), "old_names": olds,
                    "line": line_no,
                })
    return merge_duplicates(rows, problems), problems, skipped


def merge_duplicates(rows, problems):
    """One row per (program, address): same name merges; different names are reported."""
    by_key = {}
    out = []
    for r in rows:
        key = (r["program"], r["address"])
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = r
            out.append(r)
            continue
        if prev["name"] != r["name"]:
            problems.append(f"line {r['line']}: {r['program']} {fmt_addr(r['address'])} is named "
                            f"`{r['name']}` here but `{prev['name']}` on line {prev['line']}; kept the first")
            continue
        if EVIDENCE_ORDER.index(r["evidence"]) < EVIDENCE_ORDER.index(prev["evidence"]):
            prev["evidence"] = r["evidence"]
            prev["notes"] = r["notes"]
        if r["section"] not in prev["section"].split(" | "):
            prev["section"] += " | " + r["section"]
        prev["old_names"] = sorted(set(prev["old_names"]) | set(r["old_names"]))
    return out


# --------------------------------------------------------------------------------------------------
# Kinds


def assign_kinds(rows, problems):
    """A name that starts with g_ is a global, any other is a function. (check_registry.py checks the addresses against the executables.)"""
    for r in rows:
        r["kind"] = "global" if r["name"].startswith("g_") else "function"
    return rows


def read_registry(path=REGISTRY_CSV):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["address"] = int(row["address"], 16)
            rows.append(row)
    return rows


def write_registry(rows, path=REGISTRY_CSV):
    rows = sorted(rows, key=lambda r: (r["program"] != "MAGIC", r["kind"], r["address"]))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(FIELDS)
        for r in rows:
            w.writerow([r["program"], fmt_addr(r["address"]), r["name"], r["kind"], r["evidence"],
                        r["section"], r["notes"]])
