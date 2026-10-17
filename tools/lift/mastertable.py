"""
mastertable.py - find the master card table of a program from its machine image alone.

The master table is an array of fixed-size records in the program's data; one field of each record (+0x10 in every build seen) is the address of the code that implements the card's
rules, so the table is found as the longest run of records, `stride` bytes apart, whose field points into the program's code. 1.0 has 463 records of 0x34 bytes (MAGIC.EXE and
DUEL.EXE), Spells of the Ancients 622 of 0x48 (shandalar.exe and magic.exe). `find` returns the address of the first record and the number of records; a run is the table only if it is
long (MIN_RECORDS), so a program with no such table (a stub, a small program) gets none. A record whose field is not a code address ends the run, so a table that has padding in the middle
would be counted short; the card handlers are lifted from what is found, and the lifter reports what it did not reach.

tools/research/sotamaster.py is the command line of the same search.
"""
import struct
import warnings

warnings.simplefilter("ignore")
import pefile  # noqa: E402

MIN_RECORDS = 64


def code_range(pe):
    """(lo, hi) of the program's executable sections, as virtual addresses."""
    base = pe.OPTIONAL_HEADER.ImageBase
    text = [(base + s.VirtualAddress, base + s.VirtualAddress + s.Misc_VirtualSize) for s in pe.sections if s.Characteristics & 0x20000000]
    return min(a for a, _ in text), max(b for _, b in text)


def find(pe, stride, field=0x10):
    """(address of the first record, number of records) of the longest run of records `stride` bytes apart whose dword at +`field` is an address in the code; (0, 0) if there is none."""
    base = pe.OPTIONAL_HEADER.ImageBase
    lo, hi = code_range(pe)
    best = (0, 0)
    for s in pe.sections:
        if s.Characteristics & 0x20000000 or not s.SizeOfRawData:
            continue
        data = s.get_data()
        va = base + s.VirtualAddress
        n = len(data) // 4
        words = struct.unpack("<%dI" % n, data[:n * 4])
        ok = [lo <= w < hi for w in words]
        step = stride // 4
        i = 0
        while i < n:
            if not ok[i]:
                i += 1
                continue
            run, j = 0, i
            while j < n and ok[j]:
                run += 1
                j += step
            if run > best[1]:
                best = (va + i * 4 - field, run)
            i += 1
    return best if best[1] >= MIN_RECORDS else (0, 0)


def handler_addresses(pe, master, stride, field=0x10):
    """The distinct code pointers (record +`field`) of the table at `master`, in order of first use, as many records as there are."""
    base = pe.OPTIONAL_HEADER.ImageBase
    lo, hi = code_range(pe)
    out, bad = [], 0
    for i in range(2000):
        try:
            h = struct.unpack_from("<I", pe.get_data(master + i * stride - base, stride), field)[0]
        except Exception:      # noqa: BLE001  (the table ends at the end of the data)
            break
        if lo <= h < hi:
            bad = 0
            if h not in out:
                out.append(h)
        else:
            bad += 1
            if bad >= 3:
                break
    return out
