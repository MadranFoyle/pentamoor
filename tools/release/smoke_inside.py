#!/usr/bin/env python3
"""
smoke_inside.py - the parts of the archive smoke test (smoke_archive.py) that have to run with the ARCHIVE's own Python, inside the unpacked archive, the way a user's install does.

    <archive python> -I smoke_inside.py lift ROOT
    <archive python> -I smoke_inside.py build-stub ROOT OUTDIR
    <archive python> -I smoke_inside.py install ROOT DISC KNOWN_JSON        (DISC - : no disc given, the game is installed already)

Uses only the standard library and the archive's own tools/ (nothing of the repository this file lives in is imported), because on Windows that Python is the embeddable one, which
has no pip, no pytest, and ignores PYTHONPATH.

  lift         lifts three hand-assembled x86 functions to C with the archive's lifter (tools/lift/x86lift.py, capstone from the archive's tools/pydeps)
  build-stub   builds the stub game module (src/port/stubgame, hand-written) with the compiler the installer picks here (modbuild.find_compiler, nothing downloaded) into OUTDIR
  install      runs the archive's installer (install.main, what pentamoor-install runs) on a made-up 1.0-shaped disc (tools/release/smoke_install.py makes it): everything it does with
               a disc is real (reading the ISO, unpacking the game's own archive format, the media copy, the check of the programs against the table of known builds, the compiler
               choice, compiling and linking three modules, loading each into the runtime). Two things are replaced, and the output says so: the table of known builds holds the
               made-up files' hashes instead of the retail disc's, and the lifter's step is skipped (the made-up programs are not PE files); the C it would have written is
               the stub module's own, so the three modules the installer builds are three stub modules.
"""
import json
import os
import shutil
import sys

LIFT_FUNCTIONS = {                       # the same hand-assembled functions tools/lift/test_lift.py uses
    "Test_Add": (0x1000, bytes.fromhex("8b442404" "03442408" "c3")),
    "Test_Max": (0x2000, bytes.fromhex("8b442404" "3b442408" "7d04" "8b442408" "c3")),
    "Test_Switch": (0x3000, bytes.fromhex("8b442404" "83f802" "7725" "ff248510300000" "1c300000" "22300000" "28300000"
                                          "b80a000000c3" "b814000000c3" "b81e000000c3" "b8ffffffffc3")),
}


def paths(root):
    for p in (os.path.join(root, "tools", "install"), os.path.join(root, "tools", "lift"), os.path.join(root, "tools", "pydeps")):
        sys.path.insert(0, p)


def cmd_lift(root):
    paths(root)
    import capstone
    from x86lift import Lifter, Unsupported
    print(f"python {sys.version.split()[0]} {sys.executable}")
    print(f"capstone {capstone.__version__} from {os.path.dirname(capstone.__file__)}")

    def get(va, n):
        for addr, code in LIFT_FUNCTIONS.values():
            if addr <= va < addr + len(code):
                return code[va - addr:va - addr + n] + b"\x90" * 64
        raise Unsupported(f"0x{va:x} is not in the test image")

    lifter = Lifter()
    for name, (addr, code) in LIFT_FUNCTIONS.items():
        src = lifter.lift_function(get, addr, name, frozenset())[0]
        if f"lifted_{addr:08x}" not in src or "R_eax" not in src:
            print(f"the lifted C of {name} does not look like a lifted function")
            return 1
        print(f"lifted {name}: {len(src)} bytes of C")
    return 0


def cmd_build_stub(root, outdir):
    paths(root)
    import modbuild
    layout_port, layout_native = os.path.join(root, "src", "port"), os.path.join(root, "src", "native")
    cc = modbuild.find_compiler(layout_native, os.path.join(root, "tools", "local"), download=False, say=print)
    print(f"compiler: {cc.describe()}")
    with __import__("tempfile").TemporaryDirectory(prefix="pentamoor-stub-") as d:
        made = modbuild.build_modules(["stubgame"], layout_port, layout_port, layout_native, os.path.join(d, "obj"), outdir, cc, 2, print)
    print(f"module: {made['stubgame']}")
    return 0


def cmd_install(root, disc, known):
    paths(root)
    import builds
    import install

    with open(known, encoding="utf-8") as f:
        builds.KNOWN = [tuple(r) for r in json.load(f)]
    install.FINGERPRINTS = builds.fingerprints("v1.0")
    print("SMOKE NOTE: the table of known builds holds the made-up files' hashes instead of the retail disc's; the lifter's step is skipped")
    stub = os.path.join(root, "src", "port", "stubgame", "handlers_gen.c")
    for prog in ("lift_magic_all", "lift_deck", "lift_duel"):
        d = os.path.join(root, "sources", "generated", prog)
        os.makedirs(d, exist_ok=True)
        shutil.copyfile(stub, os.path.join(d, "handlers_gen.c"))

    def no_lift(layout, args, sota=None, with_licence=False):
        install.say("(smoke test: lifting skipped; sources/generated holds the stub module's C for each of the three programs)")

    install.lift = no_lift
    install.main(([disc] if disc != "-" else []) + ["--yes", "--no-download", "--jobs", "2"], default_build=True)
    return 0


def main(argv):
    if len(argv) >= 3 and argv[1] == "lift":
        return cmd_lift(argv[2])
    if len(argv) >= 4 and argv[1] == "build-stub":
        return cmd_build_stub(argv[2], argv[3])
    if len(argv) >= 5 and argv[1] == "install":
        return cmd_install(argv[2], argv[3], argv[4])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
