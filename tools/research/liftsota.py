#!/usr/bin/env python3
"""
liftsota.py - run the lifter on another build of the game (Spells of the Ancients 2.0) without editing it.

tools/lift/gen_handlers.py is tied to version 1.0: PROGRAMS holds the master card table's address and the code range of MAGIC.EXE and DUEL.EXE, VARIADIC the addresses of the
C runtime's variadic functions that DUEL.EXE carries, `native_entries` reads src/native/layout.c and `handler_addresses` reads the table with 1.0's record size (0x34). This
wrapper registers a program under another name, replaces those, and runs gen_handlers.main() as it is. Nothing is written into the repository: the output goes where --out says
(sources/generated_sota/...). The generated module's LIFT_PROGRAM is the upper-cased name, so the port's checks for "MAGIC" and "DUEL" (pace.c, screens.c, yesno.c, textfocus.c,
main.c, lzw.c) do not recognise it and their hooks, which are keyed to 1.0's addresses, are not installed.

    liftsota.py --name sota_shandalar --exe .../shandalar.exe --master 0x570cec --stride 0x48 --code-hi 0x562000 --out sources/generated_sota/lift_shandalar
    liftsota.py dll LIB.dll,LIB.dll --dll .../cardartlib.dll --base 0x34000000 --out ...      the libraries (gen_dll.py with the extra signatures)

--master is the address a record's field at +0x10 belongs to: the first code pointer of the table minus 0x10. --stride is the record size (0x34 in 1.0, 0x48 in 2.0).
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIFT = os.path.join(HERE, "..", "lift")
sys.path.insert(0, LIFT)

import gen_handlers as gh  # noqa: E402
import import_signatures as sigs  # noqa: E402

# Windows calls that only the 2.0 programs make (found by sotaimports.py), with their documented number of stack words. The lifter refuses a function that calls an import it has
# no signature for, so these are added to its tables for this run; the table in tools/lift would take them as they are.
EXTRA_STDCALL = {
    "ResumeThread": 1, "SuspendThread": 1, "WinExec": 2, "GetWindowsDirectoryA": 2, "GetVersionExA": 1, "GetDiskFreeSpaceA": 5, "GetThreadTimes": 5, "TlsAlloc": 0, "TlsFree": 1,
    "TlsGetValue": 1, "TlsSetValue": 2, "GetLocaleInfoA": 4, "GetLocaleInfoW": 4, "GetVolumeInformationA": 8, "CreateProcessA": 10, "FindFirstFileA": 2, "FindClose": 1,
    "SetRectEmpty": 1, "GetUpdateRect": 3, "GetUpdateRgn": 3, "EqualRect": 2, "ChangeDisplaySettingsA": 2, "RegisterWindowMessageA": 1, "IsDialogMessageA": 2,
    "GetWindowTextLengthA": 1, "IsCharAlphaNumericA": 1, "CreateDialogParamA": 5, "ShowScrollBar": 3, "GetCursor": 0, "CharLowerA": 1, "CharUpperA": 1, "RectInRegion": 2,
    "ExtTextOutA": 8, "GetFileTitleA": 3, "RegOpenKeyA": 3, "RegCreateKeyA": 3, "mciSendCommandA": 4, "mciGetErrorStringA": 3, "GetCurrentThreadId": 0, "SetLastError": 1,
}
EXTRA_CDECL = {"longjmp": 2, "_setjmp3": 2, "qsort": 4, "strcoll": 2, "_beginthreadex": 6, "_spawnl": sigs.VARIADIC_WORDS, "_findfirst": 2, "_findnext": 2, "_findclose": 1}


def export_signatures(dlls):
    """The calling convention of every function the game's own libraries export, read off their machine code: stdcall (the `ret` pops) or cdecl (it does not)."""
    sys.path.insert(0, HERE)
    import sotacmp as sc  # noqa: PLC0415
    out = {}
    for path in dlls:
        img = sc.Image(path)
        funcs, _ = sc.scan_functions(img)
        for a, name in img.exports.items():
            f = funcs.get(a)
            if f is None:
                continue
            pops = max((i.operands[0].imm for i in f.insns if i.mnemonic == "ret" and i.operands), default=0)
            out[(os.path.basename(path).lower(), name)] = (max(f.nargs, pops // 4), pops)
    return out


def patch_signatures(export_dlls=()):
    sigs.STDCALL.update(EXTRA_STDCALL)
    sigs.CDECL.update(EXTRA_CDECL)
    for (dll, name), (n, pops) in export_signatures(export_dlls).items():
        if pops:
            sigs.STDCALL[name] = n
        else:
            sigs.CDECL_OTHER[(dll, name)] = n          # signature() looks the C calling convention up by library, outside the C runtime


def main_dll(argv):
    """liftsota.py dll LIB,LIB... [gen_dll.py arguments]: gen_dll.py with the extra signatures (the libraries' own exports are read from the LIBs)."""
    import gen_dll  # noqa: PLC0415
    patch_signatures([x for x in argv[0].split(",") if x])
    sys.argv = ["gen_dll.py"] + argv[1:]
    gen_dll.main()


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "dll":
        return main_dll(sys.argv[2:])
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--name", required=True, help="the program's name for the lifter (becomes LIFT_PROGRAM, upper case)")
    ap.add_argument("--exe", required=True)
    ap.add_argument("--master", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--stride", type=lambda s: int(s, 0), default=0x34)
    ap.add_argument("--code-hi", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--libs", default="", help="the game's own libraries whose exports the program imports: paths, comma-separated (their calling conventions are read from their code)")
    ap.add_argument("--native", default="", help="addresses (hex, comma-separated) of functions that stand in for natives (src/native/layout.c's entries, found in this build)")
    ap.add_argument("--variadic", default="", help="addresses (hex, comma-separated) of variadic functions of the program's own C runtime")
    ap.add_argument("rest", nargs="*", help="further arguments for gen_handlers.py (default: --all --no-handlers)")
    args = ap.parse_args()

    stride = args.stride
    natives = {int(x, 16) for x in args.native.split(",") if x}

    def handler_addresses(pe, master, code):
        base = pe.OPTIONAL_HEADER.ImageBase
        out, bad = [], 0
        for i in range(2000):
            h = struct.unpack_from("<I", pe.get_data(master + i * stride - base, stride), 0x10)[0]
            if code[0] <= h < code[1]:
                bad = 0
                if h not in out:
                    out.append(h)
            else:
                bad += 1
                if bad >= 3:
                    break
        return out

    patch_signatures([x for x in args.libs.split(",") if x])
    gh.PROGRAMS[args.name] = dict(master=args.master, code=(0x401000, args.code_hi))
    gh.VARIADIC[args.name] = {int(x, 16) for x in args.variadic.split(",") if x}
    gh.handler_addresses = handler_addresses
    gh.native_entries = lambda program: set(natives)
    sys.argv = ["gen_handlers.py", "--program", args.name, "--exe", args.exe, "--out", args.out] + (args.rest or ["--all", "--no-handlers"])
    gh.main()


if __name__ == "__main__":
    main()
