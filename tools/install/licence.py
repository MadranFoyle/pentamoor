"""
licence.py - the installer's licence step for Spells of the Ancients 2.15: after the owner's discs have been verified, do what the original installer did.

The original installer (InstallShield, Setup/setup.ins on the expansion's disc) checked both discs, copied the files, and then loaded a library of its own cabinet that is installed as
Program\\DuelSounds\\Manaball.wav (internal name SencLib.dll) and called its export WriteProgramFlags with a constant flag word: that is how the machine-bound registry value
`SerialNumber` came to exist on an owner's machine (docs/notes/sota-licence.md). This module does the same, on the owner's machine, into the owner's install:

  * only the installer calls it, only after the discs and the patch were verified and the files were made (install.py), and never the runtime on its own, a launcher, or a game start;
  * the library is the owner's own file from the owner's own cabinet. Its hash is checked before it is lifted or run (tools/lift/builds.py, SOTA_LICENCE_LIBRARY), and it is run as a
    black box by the runtime (pentamoor-run --call-export, src/port/main.c) from a module lifted from that file on this machine, which is never committed or put in a release;
  * the only thing supplied here is the flag word: the licence flags the original installer set (below) and, unless the owner says --keep-cd-check, the one more that the game defines as
    "skip the disc check" (the discs were just verified, so the install does not ask for one later);
  * the value is bound to this install: the runtime answers the two Windows values the library reads from a random pair made for this install (regstore.py), kept in the install's
    overlay (port_overlay_sota/registry.dat), and the library's own write goes into the same file.

Nothing here makes, reads, encodes, checks or describes a SerialNumber. It does not know what the library writes: it only looks for the value's presence afterwards.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lift"))

import builds  # noqa: E402
import regstore  # noqa: E402

# ---- the flag word ------------------------------------------------------------------------------------------------------------------------------------------------
# WHICH LICENCE FLAGS THE ORIGINAL INSTALLER SET. The compiled script (Setup/setup.ins) is not documented anywhere, and decoding it was not part of the research (docs/notes/sota-licence.md,
# "What was established"): the flag word is read from a run of the real installer, not from the disc, and held here as named bits. A bit number is the bit of the flag word; the
# last column says what the game does with it (the checker's query mask in brackets).
FLAG_SET1_CARDS = 8             # the cards of "set 1" are available to the card pickers and the deck editor                    (query 2)
FLAG_ORIGINAL_INSTALLER = 22    # set by the original installer; the one test of it in the game is never reached (nothing asks query 1)
ORIGINAL_BITS = (FLAG_SET1_CARDS, FLAG_ORIGINAL_INSTALLER)
# NOT set by the original installer. Set here by default since 2026-10-22, because the discs were just verified (docs/notes/sota-licence.md, "What the installer does now"); left out with
# --keep-cd-check, which gives the word the original installer's own bits and nothing more.
FLAG_NO_CD_CHECK = 17           # the game skips its own disc check                                                                (query 8)
DEFAULT_BITS = ORIGINAL_BITS + (FLAG_NO_CD_CHECK,)


def flag_word(keep_cd_check=False):
    """The flag word handed to the library: by default the bits the original installer set and the one flag the game defines as "skip the disc check" (DEFAULT_BITS); with `keep_cd_check`
    (--keep-cd-check) exactly the bits the original installer set. Nothing else, ever."""
    word = 0
    for bit in (ORIGINAL_BITS if keep_cd_check else DEFAULT_BITS):
        word |= 1 << bit
    return word


def bits_of(word):
    return [b for b in range(32) if word >> b & 1]


SAY_WHAT = ("writing the licence value the original Spells of the Ancients installer writes for an owner of the discs, and, because the discs were just verified, the game's own "
            "\"skip the disc check\" flag, so this install does not ask for a disc later (--keep-cd-check keeps the check)")
SAY_KEEP_CD_CHECK = ("writing the licence value the original Spells of the Ancients installer writes for an owner of the discs, without the \"skip the disc check\" flag "
                     "(--keep-cd-check): this install asks for a disc where the original did")


class LicenceError(Exception):
    pass


# ---- where things are ---------------------------------------------------------------------------------------------------------------------------------------------
def library_path(program):
    """The path of the licence library in a 2.15 Program folder, in the spelling the folder has (the install's names are not in one case); None if it is not there."""
    here = program
    for part in builds.SOTA_LICENCE_LIBRARY["path"].split("/"):
        found = None
        for n in os.listdir(here) if os.path.isdir(here) else ():
            if n.lower() == part.lower():
                found = n
                break
        if found is None:
            return None
        here = os.path.join(here, found)
    return here if os.path.isfile(here) else None


def verify_library(path):
    """Raises LicenceError unless the file is the library of the retail cabinet (size and SHA-256 of builds.SOTA_LICENCE_LIBRARY)."""
    spec = builds.SOTA_LICENCE_LIBRARY
    if path is None or not os.path.isfile(path):
        raise LicenceError(f"{spec['path']} is not in the 2.15 install: the licence value is not written")
    size = os.path.getsize(path)
    if size != spec["size"]:
        raise LicenceError(f"{path} is {size:,} bytes where the retail cabinet's {spec['file']} is {spec['size']:,}: it is not the file the original installer used, so it is not run and "
                           "the licence value is not written")
    got = builds.file_build_id(path)
    if got != spec["sha256"]:
        raise LicenceError(f"{path} has SHA-256 {got[:16]}... where the retail cabinet's {spec['file']} has {spec['sha256'][:16]}...: it is not the file the original installer used, "
                           "so it is not run and the licence value is not written")


def overlay_dir(root, environ=None):
    """The overlay of the 2.15 install, where the registry file goes: $PORT_OVERLAY, else port_overlay_sota, a relative name being relative to the folder of the launchers (which is
    where ./pentamoor runs from)."""
    environ = os.environ if environ is None else environ
    name = environ.get("PORT_OVERLAY") or "port_overlay_sota"
    return name if os.path.isabs(name) else os.path.join(root, name)


def registry_file(overlay):
    return os.path.join(overlay, "registry.dat")


# ---- running the library ------------------------------------------------------------------------------------------------------------------------------------------
class Request:
    """What the writer is asked to do: run `export` of `library` (the owner's file) with the flag word, in the module lifted from it, with `overlay` as the place the registry file is."""

    def __init__(self, runtime, module, library, root, overlay, export, word):
        self.runtime, self.module, self.library, self.root, self.overlay, self.export, self.word = runtime, module, library, root, overlay, export, word

    def argv(self):
        return [self.runtime, "-m", self.module, "--call-export", f"{self.export}=0x{self.word:x}", self.library, self.root]

    def env(self):
        env = dict(os.environ)
        env.update({"PORT_HEADLESS": "1", "PORT_OVERLAY": self.overlay, "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"})
        for k in ("PORT_CONTROL", "PORT_SCRIPT", "PORT_TRACE", "PORT_TRACE_IMPORTS", "PORT_WHO", "PORT_UNKNOWN_BUILD"):
            env.pop(k, None)
        return env


RETURNED = re.compile(r"^export (\S+) returned (\d+)\s*$", re.M)


def run_writer(req, timeout=300):
    """Start the runtime on the library and return (exit status, what the export returned or None, the runtime's output). The real writer; the tests give another with the same shape."""
    try:
        r = subprocess.run(req.argv(), env=req.env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", timeout=timeout, cwd=req.root)
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, None, str(e)
    m = RETURNED.search(r.stdout)
    return r.returncode, int(m.group(2)) if m else None, r.stdout


def write_value(program, root, overlay, runtime, module, keep_cd_check=False, say=print, writer=run_writer):
    """The licence step. `program`: the 2.15 Program folder (verified by the caller), `root`: the root of the launchers, `overlay`: the 2.15 install's overlay, `runtime` and `module`: the
    runtime and the module lifted from the licence library. Raises LicenceError, having written nothing, when the library is not the retail file or the module is not built; and, if the
    library's export fails or leaves no value, after saying so. Returns the path of the registry file."""
    spec = builds.SOTA_LICENCE_LIBRARY
    lib = library_path(program)
    verify_library(lib)
    if not os.path.isfile(module):
        raise LicenceError(f"the module made from {spec['file']} ({module}) is not built: the licence value is not written")
    if not os.path.exists(runtime):
        raise LicenceError(f"the runtime ({runtime}) is not built: the licence value is not written")
    reg = registry_file(overlay)
    word = flag_word(keep_cd_check)
    say(f"licence: {SAY_KEEP_CD_CHECK if keep_cd_check else SAY_WHAT}")
    try:
        if regstore.ensure_pair(reg):
            say(f"licence: made this install's own machine id (two random numbers) in {reg}")
    except regstore.RegError as e:
        raise LicenceError(str(e)) from e
    code, returned, output = writer(Request(runtime, module, lib, root, overlay, spec["export"], word))
    if code != 0 or returned != 0:
        tail = "\n".join((output or "").strip().splitlines()[-8:])
        raise LicenceError(f"the original installer's library did not write the licence value (the runtime ended with status {code}, the export returned {returned}):\n{tail}")
    store = regstore.Store(reg)
    got = store.get(regstore.LICENCE_KEY, "SerialNumber")
    if not got or not got[1]:
        raise LicenceError(f"the library said it wrote the licence value but {reg} holds none")
    say(f"licence: written to {reg} (bound to this install's machine id; deleting that file takes it away, running the installer again writes it again)")
    return reg
