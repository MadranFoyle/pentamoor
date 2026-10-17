"""
libsigs.py - the calling convention of what the game's own libraries export, read from their machine code.

A program of the game (shandalar.exe) calls functions of libraries that come with it (cardartlib.dll, drawcardlib.dll, CdTools.dll, deckdll.dll). Nothing documents them: the lifter
needs, for each call, how many stack words it passes and how many bytes the callee pops (`ret imm16`: stdcall; a plain `ret`: cdecl, the caller pops), and the only place to read
that is the library itself. For each export this takes what the function's frame reads and what its `ret` pops, following a jump the linker put at its start (a thunk) to the function
it stands for.

    register(pe, program_path)    reads the libraries a program imports from its own folder and puts their exports into import_signatures.LIBRARY, where `signature` finds them

A library is "the game's own" when its file is in the program's folder and Windows does not supply a library of that name (SYSTEM_DLLS): the 2.15 install carries the C runtime
`MSVCRT.DLL` too, which the port provides itself.
"""
import os

import pefile

import import_signatures
from x86lift import Lifter, Unsupported

# Libraries Windows (or the port, for the C runtime) provides: never read from the game's folder even if a copy of one is there.
SYSTEM_DLLS = frozenset((
    "kernel32.dll", "user32.dll", "gdi32.dll", "advapi32.dll", "shell32.dll", "comctl32.dll", "comdlg32.dll", "winmm.dll", "msvfw32.dll", "avifil32.dll", "ole32.dll", "oleaut32.dll",
    "version.dll", "wsock32.dll", "ws2_32.dll", "dplayx.dll", "dsound.dll", "ddraw.dll", "msvcrt.dll", "msvcrtd.dll", "msvcrt40.dll", "mfc42.dll", "mfc42d.dll", "msvcirt.dll", "ntdll.dll",
))


def find_in_folder(folder, name):
    """The path of the file called `name` in `folder`, ignoring the case of its name (the install's names are not in one case); None if there is none."""
    if not os.path.isdir(folder):
        return None
    for n in os.listdir(folder):
        if n.lower() == name.lower():
            return os.path.join(folder, n)
    return None


def own_libraries(pe, folder):
    """{library name (lower case): path} of the game's own libraries that `pe` imports and that are in `folder`."""
    out = {}
    for d in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        name = d.dll.decode().lower()
        if name in SYSTEM_DLLS or name in out:
            continue
        path = find_in_folder(folder, name)
        if path:
            out[name] = path
    return out


def export_signatures(path):
    """{export name: (stack words, bytes the callee pops)} for the functions the library at `path` exports (data exports are left out)."""
    pe = pefile.PE(path)
    base = pe.OPTIONAL_HEADER.ImageBase
    sect = [(s.VirtualAddress + base, s.VirtualAddress + base + max(s.Misc_VirtualSize, s.SizeOfRawData)) for s in pe.sections]
    text = [(s.VirtualAddress + base, s.VirtualAddress + base + max(s.Misc_VirtualSize, s.SizeOfRawData)) for s in pe.sections if s.Characteristics & 0x20000000]

    def getbytes(va, n):
        for lo, hi in sect:
            if lo <= va < hi:
                return pe.get_data(va - base, min(n, hi - va))
        raise Unsupported(f"0x{va:x} is not in the image")

    lifter = Lifter()
    for d in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        for imp in d.imports:
            if imp.name:
                lifter.imports[imp.address] = imp.name.decode()
    syms = [(s.name.decode(), base + s.address) for s in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", []) if s.name]
    syms = [(n, a) for n, a in syms if any(lo <= a < hi for lo, hi in text)]
    entries = frozenset(a for _, a in syms)
    out = {}
    for name, addr in syms:
        target = addr
        for _ in range(8):                     # a thunk: `jmp rel32` at the start is the function it jumps to
            first = getbytes(target, 5)
            if first[:1] != b"\xe9":
                break
            target = (target + 5 + int.from_bytes(first[1:5], "little", signed=True)) & 0xFFFFFFFF
        pops = lifter.ret_cleanup(getbytes, target, entries)
        out[name] = (max(lifter.callee_arguments(getbytes, target, entries), pops // 4), pops)
    return out


def register(pe, program_path):
    """Read the exports of the game's own libraries that `pe` (the program or library at `program_path`) imports, from the folder it is in, into import_signatures.LIBRARY.
    Returns the library names found."""
    folder = os.path.dirname(os.path.abspath(program_path))
    found = own_libraries(pe, folder)
    for name, path in found.items():
        for export, sig in export_signatures(path).items():
            import_signatures.LIBRARY.setdefault((name, export), sig)
    return sorted(found)
