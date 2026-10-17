#!/usr/bin/env python3
"""deploy: put Pentamoor on an iPad (or in the iOS Simulator) with one command (docs/notes/ios.md, "One command"). Run it through deploy.sh.

    tools/ios/deploy.sh --team ABCDE12345                  build, install, copy the game in, start it (the only iPad that is connected)
    tools/ios/deploy.sh --dry-run                          print every command it would run, change nothing
    tools/ios/deploy.sh --simulator [UDID|NAME]            the same steps for a Simulator (xcodebuild + simctl instead of devicectl)
    tools/ios/deploy.sh --selftest                         check that every option of xcodebuild, devicectl and simctl used here exists in this Xcode

The steps, each one printing one line, each one safe to repeat:
  1 prerequisites  macOS, Xcode (xcodebuild, the iphoneos SDK, devicectl), the game folder, and where the game's code comes from: objects built beforehand (the iPad kit, see below) or the lifted C
  2 device         the iPad, found with `devicectl list devices` (JSON, not the table): paired, reachable, Developer Mode on, unlocked
  3 signing        the team (--team, else $PENTAMOOR_TEAM, else PENTAMOOR_TEAM in ~/.config/pentamoor/ios.env, else the one Apple Development certificate in the keychain) and a bundle id
                   (the same order for --bundle-id; default com.<you>.pentamoor). The settings file takes PENTAMOOR_TEAM=, PENTAMOOR_BUNDLE_ID= and PENTAMOOR_DEVICE= lines, nothing else, nothing evaluated.
  4 project        tools/ios/gen_xcodeproj.py writes the Xcode project (with --prebuilt for a kit)
  5 build          xcodebuild for the device, automatic signing (-allowProvisioningUpdates), incremental after the first time
  6 install        devicectl device install app
  7 data           the game's folder into the app's Documents/Magic, unless the same data is already there (a stamp file is compared), so a new build takes seconds
  8 launch         devicectl device process launch --terminate-existing   (--console follows the app's output)

Two kinds of checkout run this. A repository with the game installed and lifted (sources/generated, sources/installed/Magic) builds everything itself. An "iPad kit" (kit-manifest.json at its top, made on the
Mac that has the game by sources/kits/make-ipad-kit.sh, which is not in the repository) carries the three game modules and SDL2 already compiled (prebuilt/), the game's folder (Magic/), and
the runtime's sources: this Mac only compiles those, links, signs and installs. Nothing here touches a keychain, an account or a profile; xcodebuild does that itself, with -allowProvisioningUpdates,
using the Apple ID signed in to Xcode.

Python 3.9 (/usr/bin/python3 on a Mac) is enough; nothing is installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

APP = "Pentamoor"
DATA_DIR = "Documents/Magic"                    # where the app looks for the game (iosboot.h)
STAMP_FILE = "Documents/pentamoor-data.stamp"   # what deploy copied last: compared, so the same data is not copied twice
PROGRAM_FILE = "Documents/program.txt"
LOG_FILE = "Documents/pentamoor.log"
PROBE_DIR = "Documents/.pentamoor-probe"        # a few bytes, to learn how `devicectl device copy to` treats a directory (see Deployer.copy_layout)
MIN_IOS = 15
MIN_XCODE = 15                                  # devicectl came with Xcode 15
TESTED_XCODE = "27.0"                           # the only Xcode that has built and run this (docs/notes/ios.md, "What was tested")

# Every option of the tools that the commands below use; `--selftest` checks them against each tool's own help, and test_deploy.py checks that no command uses one that is not here.
TOOL_FLAGS = {
    ("xcodebuild",): ["-project", "-scheme", "-configuration", "-destination", "-derivedDataPath", "-allowProvisioningUpdates", "-allowProvisioningDeviceRegistration", "-quiet"],
    ("xcrun", "devicectl", "list", "devices"): ["--json-output"],
    ("xcrun", "devicectl", "device", "info", "lockState"): ["--device", "--json-output"],
    ("xcrun", "devicectl", "device", "info", "files"): ["--device", "--domain-type", "--domain-identifier", "--subdirectory", "--no-recurse", "--json-output"],
    ("xcrun", "devicectl", "device", "install", "app"): ["--device"],
    ("xcrun", "devicectl", "device", "copy", "to"): ["--device", "--source", "--destination", "--domain-type", "--domain-identifier"],
    ("xcrun", "devicectl", "device", "copy", "from"): ["--device", "--source", "--destination", "--domain-type", "--domain-identifier"],
    ("xcrun", "devicectl", "device", "process", "launch"): ["--device", "--terminate-existing", "--console"],
    ("xcrun", "simctl", "install"): [],
    ("xcrun", "simctl", "launch"): ["--console", "--terminate-running-process"],
    ("xcrun", "simctl", "get_app_container"): [],
    ("xcrun", "simctl", "bootstatus"): ["-b"],
    ("xcrun", "simctl", "list"): ["--json"],
}


class StopDeploy(Exception):
    """Nothing more to do (--list-devices)."""


class Fail(Exception):
    """Something to stop for: a sentence and, optionally, what to do about it."""

    def __init__(self, message, hint=None):
        Exception.__init__(self, message)
        self.hint = hint


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------
# Pure helpers (tools/ios/test_deploy.py tests them without Xcode, a device or the game)
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def is_mac():
    return sys.platform == "darwin"


def sanitize_user(name):
    """A login name as a bundle id part: lower-case letters, digits and hyphens."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "user"


def default_bundle_id(user=None):
    return "com.%s.pentamoor" % sanitize_user(user if user is not None else os.environ.get("USER") or os.environ.get("LOGNAME") or "")


def valid_bundle_id(s):
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", s or "")) and "." in s


CONFIG_KEYS = ("PENTAMOOR_TEAM", "PENTAMOOR_BUNDLE_ID", "PENTAMOOR_DEVICE")
SIGNING_FAILURE = re.compile(r"No Account for Team|No accounts with Apple ID|Add a new account|No profiles for|No provisioning profile|doesn't include the currently selected device|"
                             r"Failed to (create|register) provisioning|Provisioning profile .* doesn't|requires a development team|No signing certificate|valid signing identity|"
                             r"Failed Registering Bundle Identifier|ProvisioningProfile|Automatic signing|signing .* failed|Code ?Sign error", re.I)


def config_path(env=None):
    """The per-user settings file: $PENTAMOOR_IOS_CONFIG, else ~/.config/pentamoor/ios.env."""
    env = os.environ if env is None else env
    return env.get("PENTAMOOR_IOS_CONFIG") or os.path.join(os.path.expanduser("~"), ".config", "pentamoor", "ios.env")


def parse_config(text):
    """KEY=VALUE lines (a leading `export ` and one pair of quotes are allowed; # comments); only the keys in CONFIG_KEYS count. Nothing is evaluated: this is not a shell script."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, eq, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not eq or key not in CONFIG_KEYS:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def load_config(path):
    try:
        with open(path, errors="replace") as f:
            return parse_config(f.read())
    except OSError:
        return {}


def valid_team(s):
    return bool(re.fullmatch(r"[A-Z0-9]{10}", s or ""))


def team_from_subject(subject):
    """The team id in a certificate's subject line: its OU. (openssl on a Mac prints `subject= /UID=../CN=Apple Development: Name (PERSONID)/OU=TEAMID/O=Name/C=US`; OpenSSL 3 prints
    `subject=UID=.., CN=.., OU=TEAMID, O=..`. The (PERSONID) in the CN is the person's id, not the team's.)"""
    for m in re.finditer(r"(?:^|[/,]|\s)OU\s*=\s*([A-Z0-9]{10})(?=\s*(?:$|[/,]))", subject):
        return m.group(1)
    return None


def cn_from_subject(subject):
    m = re.search(r"CN\s*=\s*([^/,]+)", subject)
    return m.group(1).strip() if m else ""


def split_pems(text):
    return re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----\n?", text, re.S)


def dig(d, *paths):
    """The first value found at any of the key paths (tuples), or None."""
    for path in paths:
        cur = d
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                cur = None
                break
        if cur is not None and cur != "":
            return cur
    return None


def deep_find(d, match, skip=("capabilities",)):
    """The first value, anywhere in a nested dict, under a key for which match(key) is true."""
    if isinstance(d, dict):
        for k, v in d.items():
            if k in skip:
                continue
            if match(k):
                return v
        for k, v in d.items():
            if k in skip:
                continue
            r = deep_find(v, match, skip)
            if r is not None:
                return r
    elif isinstance(d, list):
        for v in d:
            r = deep_find(v, match, skip)
            if r is not None:
                return r
    return None


def version_text(v):
    if isinstance(v, dict):
        return str(v.get("stringValue") or ".".join(str(c) for c in (v.get("components") or [])[:3]))
    return "" if v is None else str(v)


class Device(object):
    """One row of `devicectl list devices --json-output`. The JSON has two shapes (the older hardwareProperties/deviceProperties/connectionProperties, and `properties` with hardware, connection,
    software and state in it, in which the older ones are deprecated); both are read, and a field that is in neither is empty."""

    def __init__(self, d):
        self.raw = d
        self.name = str(dig(d, ("deviceProperties", "name"), ("properties", "state", "name"), ("properties", "device", "name"), ("name",)) or "")
        self.identifier = str(d.get("identifier") or "")
        self.udid = str(dig(d, ("hardwareProperties", "udid"), ("properties", "hardware", "udid")) or "")
        self.serial = str(dig(d, ("hardwareProperties", "serialNumber"), ("properties", "hardware", "serialNumber")) or "")
        self.ecid = str(dig(d, ("hardwareProperties", "ecid"), ("properties", "hardware", "ecid")) or "")
        self.product_type = str(dig(d, ("hardwareProperties", "productType"), ("properties", "hardware", "productType")) or "")
        self.marketing = str(dig(d, ("hardwareProperties", "marketingName"), ("properties", "hardware", "marketingName")) or "")
        self.device_type = str(dig(d, ("hardwareProperties", "deviceType"), ("properties", "hardware", "deviceType")) or "")
        self.platform = str(dig(d, ("hardwareProperties", "platform"), ("properties", "hardware", "platform")) or "")
        self.reality = str(dig(d, ("hardwareProperties", "reality"), ("properties", "hardware", "reality")) or "")
        self.visibility = str(d.get("visibilityClass") or dig(d, ("properties", "state", "visibilityClass")) or "")
        self.os_version = version_text(dig(d, ("deviceProperties", "osVersionNumber"), ("properties", "software", "osVersionNumber")))
        self.pairing = str(dig(d, ("connectionProperties", "pairingState"), ("properties", "connection", "pairingState")) or "")
        self.transport = str(dig(d, ("connectionProperties", "transportType"), ("properties", "connection", "transportType")) or "")
        self.tunnel = str(dig(d, ("connectionProperties", "tunnelState"), ("properties", "connection", "state")) or "")
        dm = deep_find(d, lambda k: k.lower().startswith("developermode"))
        if isinstance(dm, bool):
            dm = "enabled" if dm else "disabled"
        self.developer_mode = str(dm or "").lower()
        self.ddi = dig(d, ("deviceProperties", "ddiServicesAvailable"), ("properties", "device", "ddiServicesAvailable"))
        hosts = []
        for path in (("connectionProperties", "localHostnames"), ("connectionProperties", "potentialHostnames"), ("properties", "connection", "localHostnames"), ("properties", "connection", "potentialHostnames")):
            v = dig(d, path)
            if isinstance(v, list):
                hosts += [str(h) for h in v]
        self.hostnames = hosts

    @property
    def is_simulator(self):
        return self.reality == "simulated" or self.visibility == "simulators" or self.transport == "sameMachine"

    @property
    def is_ipad(self):
        return self.device_type.lower() == "ipad" or self.product_type.startswith("iPad") or "ipad" in self.marketing.lower()

    @property
    def ref(self):
        """What xcodebuild's destination and devicectl's --device take: the UDID if there is one, else the CoreDevice identifier."""
        return self.udid or self.identifier

    @property
    def link(self):
        return {"wired": "USB", "localNetwork": "Wi-Fi", "sameMachine": "this Mac"}.get(self.transport, self.transport or "?")

    def os_major(self):
        m = re.match(r"\d+", self.os_version)
        return int(m.group(0)) if m else None

    def describe(self):
        bits = [self.marketing or self.product_type or "device"]
        if self.os_version:
            bits.append("%s %s" % ("iPadOS" if self.is_ipad else "iOS", self.os_version))
        if self.transport:
            bits.append(self.link)
        return "%s (%s)" % (self.name or self.ref, ", ".join(bits))

    def keys(self):
        return [k.lower() for k in [self.name, self.identifier, self.udid, self.serial, self.ecid] + self.hostnames if k]


def parse_devices(doc):
    """The devices of a `devicectl list devices --json-output` document."""
    try:
        rows = doc["result"]["devices"]
    except (KeyError, TypeError):
        raise Fail("devicectl's device list has no result.devices (an unexpected JSON shape: %s)" % (", ".join(sorted(doc)) if isinstance(doc, dict) else type(doc).__name__),
                   "update Xcode, or pass --device with the UDID and look at `xcrun devicectl list devices`")
    return [Device(r) for r in rows if isinstance(r, dict)]


def match_devices(devs, want):
    """Devices that `want` names: exactly (name, UDID, identifier, serial, ECID, host name; case does not matter), else a name that contains it."""
    w = want.strip().lower()
    exact = [d for d in devs if w in d.keys()]
    if exact:
        return exact
    return [d for d in devs if w in (d.name or "").lower()]


def device_summary_table(devs):
    rows = []
    for d in devs:
        rows.append("  %-28s %-38s %-8s %-9s %s" % ((d.name or "?")[:28], d.ref, d.link, d.pairing or "?", d.marketing or d.product_type))
    return "\n".join(rows)


def pick_device(devs, want=None):
    """The iPad to use. Raises Fail with what to do when there is none or more than one."""
    if want:
        hits = match_devices(devs, want)
        if not hits:
            real = [d for d in devs if not d.is_simulator]
            raise Fail("no device matches \"%s\"" % want, ("these are connected:\n" + device_summary_table(real)) if real else
                       "no iPad is connected: " + CONNECT_HINT)
        if len(hits) > 1:
            raise Fail("\"%s\" matches %d devices" % (want, len(hits)), "be exact (use the UDID):\n" + device_summary_table(hits))
        d = hits[0]
        if d.is_simulator:
            raise Fail("\"%s\" is a Simulator, not an iPad" % want, "use  --simulator %s" % d.ref)
        return d
    ipads = [d for d in devs if d.is_ipad and not d.is_simulator]
    if not ipads:
        others = [d for d in devs if not d.is_simulator]
        raise Fail("no iPad is connected" + (" (found: %s)" % ", ".join(d.name or d.ref for d in others) if others else ""), CONNECT_HINT)
    if len(ipads) > 1:
        raise Fail("%d iPads are connected" % len(ipads), "say which with --device NAME_OR_UDID:\n" + device_summary_table(ipads))
    return ipads[0]


CONNECT_HINT = ("plug the iPad into this Mac with a cable, unlock it, and tap Trust on the iPad if it asks; or pair it once over Wi-Fi (Xcode > Window > Devices and Simulators > the iPad > Connect via network). "
                "Then `xcrun devicectl list devices` should show it.")
DEVMODE_HINT = ("turn Developer Mode on: on the iPad, Settings > Privacy & Security > Developer Mode > on, then restart the iPad when it asks and confirm \"Turn On\" after the restart. "
                "(The switch only shows after the iPad has been connected to a Mac with Xcode once.)")


def device_problems(d):
    """What is wrong with this device for installing an app: a list of (level, sentence, hint), level "error" or "warn"."""
    out = []
    if d.is_simulator:
        out.append(("error", "%s is a Simulator" % d.name, "use  --simulator"))
    if d.platform and d.platform.lower() not in ("ios", "ipados"):
        out.append(("error", "%s runs %s, not iPadOS" % (d.name, d.platform), None))
    elif not d.is_ipad:
        out.append(("error", "%s is not an iPad (%s): the app is built for iPad only" % (d.name, d.marketing or d.product_type or d.device_type), None))
    if d.pairing and d.pairing != "paired":
        out.append(("error", "%s is not paired with this Mac (%s)" % (d.name, d.pairing), "unlock the iPad and tap Trust This Computer; if it never asks, unplug it and plug it in again. " + CONNECT_HINT))
    if d.tunnel == "unavailable":
        out.append(("error", "%s is not reachable" % d.name, "unlock it, check the cable (or that it is on the same Wi-Fi network as this Mac), and try again. " + CONNECT_HINT))
    if d.developer_mode == "disabled":
        out.append(("error", "Developer Mode is off on %s" % d.name, DEVMODE_HINT))
    elif not d.developer_mode:
        out.append(("warn", "could not tell whether Developer Mode is on", "if the install is refused, " + DEVMODE_HINT))
    major = d.os_major()
    if major is not None and major < MIN_IOS:
        out.append(("error", "%s runs iPadOS %s; the app needs %d or newer" % (d.name, d.os_version, MIN_IOS), None))
    return out


def lock_state_locked(doc):
    """Is the device locked, by the JSON of `devicectl device info lockState`? True, False, or None when the document has neither field."""
    v = deep_find(doc.get("result", doc) if isinstance(doc, dict) else {}, lambda k: k == "passcodeRequired")
    if isinstance(v, bool):
        return v
    v = deep_find(doc, lambda k: k.lower() in ("locked", "islocked"))
    return v if isinstance(v, bool) else None


def parse_simulators(doc):
    """(udid, name, state, runtime) for each available Simulator in `xcrun simctl list devices available --json`."""
    out = []
    for runtime, rows in sorted((doc.get("devices") or {}).items()):
        for r in rows:
            if r.get("isAvailable", True):
                out.append((r["udid"], r.get("name", ""), r.get("state", ""), runtime.split(".")[-1]))
    return out


def pick_simulator(sims, want):
    """The Simulator to use. want: a UDID, a name, or "auto" (the only booted iPad one)."""
    if want == "auto":
        booted = [s for s in sims if s[2] == "Booted" and "iPad" in s[1]]
        if len(booted) == 1:
            return booted[0]
        raise Fail("--simulator needs a UDID or a name" + (" (%d iPad Simulators are booted)" % len(booted) if booted else " (no iPad Simulator is booted)"),
                   "`xcrun simctl list devices available` lists them; for example  --simulator \"iPad Pro 13-inch (M5)\"")
    w = want.lower()
    hits = [s for s in sims if s[0].lower() == w] or [s for s in sims if s[1].lower() == w]
    if not hits:
        raise Fail("no Simulator matches \"%s\"" % want, "`xcrun simctl list devices available` lists them")
    booted = [s for s in hits if s[2] == "Booted"]
    if len(hits) > 1 and len(booted) == 1:
        return booted[0]
    if len(hits) > 1:
        raise Fail("\"%s\" is the name of %d Simulators" % (want, len(hits)), "use a UDID:\n" + "\n".join("  %s  %s  %s  %s" % (s[0], s[1], s[3], s[2]) for s in hits))
    return hits[0]


def fingerprint(folder):
    """(id, files, bytes) of a game folder: a hash of every file's relative path and size (Finder's .DS_Store and ._ files do not count). Cheap, and a changed or missing file changes it."""
    h = hashlib.sha256()
    files = total = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames.sort()
        for f in sorted(filenames):
            if f == ".DS_Store" or f.startswith("._"):
                continue
            p = os.path.join(dirpath, f)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            n = os.path.getsize(p)
            h.update(("%s\t%d\n" % (os.path.relpath(p, folder).replace(os.sep, "/"), n)).encode("utf-8", "surrogateescape"))
            files += 1
            total += n
    return h.hexdigest(), files, total


def make_stamp(fp):
    return json.dumps({"data_id": fp[0], "files": fp[1], "bytes": fp[2], "by": "tools/ios/deploy.sh"}, sort_keys=True) + "\n"


def stamp_id(text):
    try:
        return json.loads(text).get("data_id")
    except (ValueError, AttributeError):
        return None


def read_kit(root):
    """The kit manifest at the top of root, or None when root is a repository checkout."""
    p = os.path.join(root, "kit-manifest.json")
    if not os.path.isfile(p):
        return None
    with open(p) as f:
        return json.load(f)


def choose_libs(kit, sdk, sdk_version, rebuild=False, prebuilt=False, have_prebuilt=True):
    """Where the game's code comes from. Returns (mode, note, warning): mode "sources" (compile the lifted C: build_ios.sh libs, a repository or a kit made with --with-sources) or "prebuilt"."""
    if kit is None:
        if prebuilt:
            raise Fail("--prebuilt: this is not an iPad kit (no kit-manifest.json)", None)
        return "sources", "lifted C of this checkout", None
    built_with = ((kit.get("sdk") or {}).get(sdk) or {}).get("version", "?")
    if rebuild:
        if not kit.get("with_sources"):
            raise Fail("--rebuild: this kit has no lifted C (it was made without --with-sources)", "make the kit again with  sources/kits/make-ipad-kit.sh --with-sources")
        return "sources", "compiling the kit's lifted C (--rebuild)", None
    if prebuilt and not have_prebuilt:
        raise Fail("--prebuilt: the kit has no prebuilt objects for this SDK", None)
    if not have_prebuilt:
        if kit.get("with_sources"):
            return "sources", "the kit has no prebuilt objects; compiling its lifted C", None
        raise Fail("the kit has neither prebuilt objects nor lifted C", "make the kit again")
    if sdk_version and built_with != sdk_version and not prebuilt:
        if kit.get("with_sources"):
            return "sources", "this Mac has the %s SDK %s, the kit's objects were built with %s: compiling the kit's lifted C instead" % (sdk, sdk_version, built_with), None
        return "prebuilt", "prebuilt objects", ("the kit's objects were built with the %s SDK %s (Xcode %s), this Mac has %s: linking them may still work; if the link fails, make the kit "
                                                 "again on a Mac with this Xcode, or with --with-sources" % (sdk, built_with, (kit.get("xcode") or {}).get("version", "?"), sdk_version))
    return "prebuilt", "prebuilt objects (iphoneos SDK %s, as in the kit)" % built_with, None


HINTS = [
    (r"No Account for Team|No accounts with Apple ID|Add a new account|No account|not signed in|accountsd",
     "Xcode has no Apple ID for this team on this Mac: Xcode > Settings > Accounts > + > Apple ID (the account of the team), then run this again."),
    (r"requires a development team|Signing for .* requires",
     "no team was given to signing: pass --team TEAMID (developer.apple.com > Membership details, or Xcode > Settings > Accounts)."),
    (r"is not available to you|Failed Registering Bundle Identifier|cannot be registered to your development team|bundle identifier .* (already|not available)",
     "the bundle id is taken (by another team): choose another with --bundle-id com.<you>.pentamoor2."),
    (r"No profiles for|No provisioning profile|doesn't include the currently selected device|Provisioning profile .* doesn't|Failed to (create|register) provisioning",
     "signing could not get a provisioning profile: be sure Xcode is signed in to the account of --team (Settings > Accounts), the iPad is in Developer Mode, and the bundle id is yours; the first run needs the internet."),
    (r"maximum number of (registered )?(apps|devices)|too many (apps|devices|App IDs)|App ID limit",
     "a free developer account is limited (10 App IDs a week, 3 apps on a device): wait, or use a paid account, or delete an old app from the iPad."),
    (r"valid signing identity|no signing certificate|certificate .* (revoked|expired)|No certificate",
     "no usable signing certificate: Xcode > Settings > Accounts > Manage Certificates > + Apple Development."),
    (r"Developer Mode|developer mode",
     DEVMODE_HINT),
    (r"[Dd]evice is locked|is locked|passcode",
     "the iPad is locked: unlock it (and keep it awake) and run again."),
    (r"Unable to find a destination|Unable to find a device matching|[Cc]ould not find device|[Nn]o devices? found|no device matching|isn't connected|not connected|Device not found",
     "the iPad was not found: " + CONNECT_HINT),
    (r"doesn't support iOS|not supported by this version of Xcode|requires a newer version of Xcode|iOS [0-9.]+ is not installed|DeviceSupport|needs a newer Xcode|platform .* not installed|Unsupported (iOS|OS) version",
     "this Xcode is too old for the iPad's iPadOS (or its iOS platform is not installed): update Xcode (Settings > Components for the platform)."),
    (r"built for newer|was built with a newer|object file .* built for|ld: .*(archive|object).* (iOS|SDK)|incompatible|Undefined symbols|symbol\(s\) not found|duplicate symbol",
     "the prebuilt objects do not link with this Xcode/SDK: use a kit made with --with-sources (deploy.sh --rebuild compiles it), or make the kit on this Xcode."),
    (r"invalid code signature|has not been explicitly trusted|[Uu]ntrusted|inadequate entitlements|profile has not been",
     "on the iPad: Settings > General > VPN & Device Management > (your Apple ID under Developer App) > Trust, then open the app. Entitlements: try without --entitlements."),
    (r"No space left|not enough space",
     "no space left (on this Mac or on the iPad; the game is 280 MB)."),
    (r"[Tt]imed out|timeout",
     "the iPad did not answer in time: unlock it, replug the cable (or stay on the same Wi-Fi) and run again."),
    (r"bundle .* (not found|isn't installed|is not installed)|application .* not (found|installed)|No such app|InvalidArguments.*bundle|unable to (find|locate) .*(app|bundle)",
     "the app is not installed on the iPad: run without --data-only first."),
]


def explain(text):
    """Hints for the failure whose output is `text` (a list of sentences, none twice)."""
    out = []
    for pat, hint in HINTS:
        if re.search(pat, text) and hint not in out:
            out.append(hint)
    return out


def error_lines(text, n=10):
    """The lines of a tool's output that say what went wrong (xcodebuild prints hundreds of others), else its last lines."""
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    errs = []
    for l in lines:
        if re.search(r"error:|error \(|Error Domain|ERROR|failed|Failed|denied|refused|not found|Unable to|Could not|cannot", l) and l not in errs:
            errs.append(l)
    return (errs or lines)[-n:]


def format_cmd(argv, env=None):
    s = " ".join(shlex.quote(a) for a in argv)
    if env:
        s = " ".join("%s=%s" % (k, shlex.quote(v)) for k, v in sorted(env.items())) + " " + s
    return s


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------
# The commands (pure: argument lists)
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def cmd_list_devices(json_path):
    return ["xcrun", "devicectl", "list", "devices", "--json-output", json_path]


def cmd_lock_state(dev, json_path):
    return ["xcrun", "devicectl", "device", "info", "lockState", "--device", dev, "--json-output", json_path]


def cmd_files(dev, bundle, subdir, json_path, recurse=False):
    return (["xcrun", "devicectl", "device", "info", "files", "--device", dev, "--domain-type", "appDataContainer", "--domain-identifier", bundle, "--subdirectory", subdir]
            + ([] if recurse else ["--no-recurse"]) + ["--json-output", json_path])


def cmd_install(dev, app):
    return ["xcrun", "devicectl", "device", "install", "app", "--device", dev, app]


def cmd_copy_to(dev, bundle, source, destination):
    return ["xcrun", "devicectl", "device", "copy", "to", "--device", dev, "--source", source, "--destination", destination,
            "--domain-type", "appDataContainer", "--domain-identifier", bundle]


def cmd_copy_from(dev, bundle, source, destination):
    return ["xcrun", "devicectl", "device", "copy", "from", "--device", dev, "--source", source, "--destination", destination,
            "--domain-type", "appDataContainer", "--domain-identifier", bundle]


def cmd_launch(dev, bundle, console=False):
    return ["xcrun", "devicectl", "device", "process", "launch", "--device", dev, "--terminate-existing"] + (["--console"] if console else []) + [bundle]


def cmd_build(project, derived, destination, team, bundle, sdk_config="Release", device=True):
    c = ["xcodebuild", "-project", project, "-scheme", APP, "-configuration", sdk_config, "-destination", destination, "-derivedDataPath", derived]
    if device:
        c += ["-allowProvisioningUpdates", "-allowProvisioningDeviceRegistration"]
    c += ["-quiet"]
    if team:
        c.append("DEVELOPMENT_TEAM=" + team)
    c.append("PRODUCT_BUNDLE_IDENTIFIER=" + bundle)
    return c + ["build"]


def cmd_sim_install(udid, app):
    return ["xcrun", "simctl", "install", udid, app]


def cmd_sim_container(udid, bundle):
    return ["xcrun", "simctl", "get_app_container", udid, bundle, "data"]


def cmd_sim_launch(udid, bundle, console=False):
    return ["xcrun", "simctl", "launch", "--terminate-running-process"] + (["--console"] if console else []) + [udid, bundle]


def cmd_sim_list():
    return ["xcrun", "simctl", "list", "devices", "available", "--json"]


def cmd_sim_boot(udid):
    return ["xcrun", "simctl", "bootstatus", udid, "-b"]


def cmd_gen_project(out_dir, team, bundle, entitlements, prebuilt_dir):
    c = [sys.executable, os.path.join(HERE, "gen_xcodeproj.py"), "--bundle-id", bundle, "--out", out_dir]
    if team:
        c += ["--team", team]
    if entitlements:
        c.append("--entitlements")
    if prebuilt_dir:
        c += ["--prebuilt", prebuilt_dir]
    return c


def built_app_path(derived, device=True):
    return os.path.join(derived, "Build", "Products", "Release-" + ("iphoneos" if device else "iphonesimulator"), APP + ".app")


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------
# Running things
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------

class Result(object):
    def __init__(self, rc=0, out=""):
        self.rc = rc
        self.out = out

    @property
    def ok(self):
        return self.rc == 0


class Runner(object):
    """Runs commands, or only prints them. Reading commands (`read`) run unless the device list came from a file (offline); changing ones (`write`) never run in a dry run."""

    def __init__(self, dry=False, offline=False, verbose=False, out=None):
        self.dry, self.offline, self.verbose = dry, offline, verbose
        self.out = out or sys.stdout
        self.log = []

    def show(self, argv, env=None, prefix="+"):
        self.out.write("%s %s\n" % (prefix, format_cmd(argv, env)))
        self.out.flush()

    def run(self, argv, kind="write", env=None, timeout=None, stream=False, logfile=None, cwd=None):
        self.log.append((kind, list(argv)))
        skip = (self.dry and kind == "write") or (self.offline and kind == "read")
        if (self.dry and kind == "write") or self.verbose:
            self.show(argv, env, "  would run:" if skip else "+")
        if skip:
            return Result(0, "")
        e = dict(os.environ)
        if env:
            e.update(env)
        try:
            if logfile:
                with open(logfile, "w") as lf:
                    p = subprocess.run(argv, stdout=lf, stderr=subprocess.STDOUT, env=e, timeout=timeout, cwd=cwd)
                with open(logfile, errors="replace") as lf:
                    return Result(p.returncode, lf.read())
            if stream:
                return Result(subprocess.run(argv, env=e, timeout=timeout, cwd=cwd).returncode, "")
            p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=e, timeout=timeout, cwd=cwd, universal_newlines=True, errors="replace")
            return Result(p.returncode, p.stdout)
        except FileNotFoundError:
            return Result(127, "%s: command not found" % argv[0])
        except subprocess.TimeoutExpired:
            return Result(124, "%s: timed out after %s s" % (argv[0], timeout))


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------
# The deployment
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------

class Deployer(object):
    def __init__(self, opts, runner=None, root=ROOT, out=None):
        self.o = opts
        self.root = root
        self.out = out or sys.stdout
        self.sim = opts.simulator is not None
        self.r = runner or Runner(opts.dry_run, bool(opts.device_json), opts.verbose, self.out)
        self.kit = read_kit(root)
        self.config_file = config_path()
        self.config = load_config(self.config_file)
        self.work = os.path.abspath(opts.work or os.path.join(root, "dist", "ios", "deploy"))
        self.tmp = None
        self.dev = None             # the Device
        self.sim_row = None         # (udid, name, state, runtime)
        self.team = None
        self.bundle = None
        self.libs = None            # "prebuilt" or "sources"
        self.layout = "target"      # copy_layout()
        self.steps = []
        self.n = 0
        self.warnings = []

    # ---- output ----
    def say(self, title, text):
        self.n += 1
        self.out.write("[%d/%d] %-13s %s\n" % (self.n, len(self.steps), title, text))
        self.out.flush()

    def note(self, text):
        self.out.write("        %s\n" % text)
        self.out.flush()

    def warn(self, text):
        self.warnings.append(text)
        self.out.write("        warning: %s\n" % text)
        self.out.flush()

    def long(self, text):
        self.out.write("        ... %s\n" % text)
        self.out.flush()

    # ---- small things ----
    @property
    def dev_ref(self):
        return self.dev.ref if self.dev else "<device>"

    def tmpfile(self, name):
        if self.tmp is None:
            self.tmp = tempfile.mkdtemp(prefix="pentamoor-deploy-")
        return os.path.join(self.tmp, name)

    def read_json(self, build, name, timeout=60):
        """Run a reading command that writes JSON (build(path) is its argument list); returns (Result, the document or None)."""
        path = self.tmpfile(name)
        if os.path.exists(path):
            os.remove(path)
        res = self.r.run(build(path), "read", timeout=timeout)
        doc = None
        if res.ok and os.path.isfile(path):
            try:
                with open(path) as f:
                    doc = json.load(f)
            except ValueError:
                doc = None
        return res, doc

    def fail_output(self, res, what):
        """Raise a Fail for a failed command, with its output tail and the hints its text calls for."""
        tail = "\n".join(error_lines(res.out))
        hints = explain(res.out)
        raise Fail("%s failed (exit %d)%s" % (what, res.rc, (":\n" + tail) if tail else ""), "\n".join(hints) if hints else None)

    def xcode_tools(self):
        """(Xcode version, build, sdk version, devicectl version) -- empty strings in a dry run without Xcode."""
        v = self.r.run(["xcodebuild", "-version"], "read", timeout=60)
        xv = xb = ""
        m = re.search(r"Xcode (\d+(?:\.\d+)*)", v.out)
        if v.ok and m:
            xv = m.group(1)
        m = re.search(r"Build version (\S+)", v.out)
        if v.ok and m:
            xb = m.group(1)
        sdk = "iphonesimulator" if self.sim else "iphoneos"
        s = self.r.run(["xcrun", "--sdk", sdk, "--show-sdk-version"], "read", timeout=60)
        sv = s.out.strip() if s.ok else ""
        dv = ""
        if not self.sim:
            d = self.r.run(["xcrun", "devicectl", "--version"], "read", timeout=60)
            dv = d.out.strip().splitlines()[-1] if d.ok and d.out.strip() else ""
        return xv, xb, sv, dv, v

    # ---- 1: prerequisites ----
    def prerequisites(self):
        o = self.o
        if not is_mac():
            if not self.r.dry:
                raise Fail("this runs on a Mac with Xcode (macOS is needed for xcodebuild, devicectl and the iOS SDK)")
        if re.search(r"\s", self.root) or re.search(r"\s", self.work):
            raise Fail("the folder path has a space in it (%s)" % (self.root if re.search(r"\s", self.root) else self.work),
                       "move the folder to a path without spaces (the Xcode project's linker settings cannot quote it), for example ~/pentamoor-ipad")
        xv, xb, sv, dv, vres = self.xcode_tools()
        problems = []
        if not self.r.offline:
            if vres.rc == 127 or not xv:
                problems.append(("Xcode's command line tools are not there (xcodebuild failed: %s)" % vres.out.strip().splitlines()[0] if vres.out.strip() else "xcodebuild is not there",
                                 "install Xcode from the App Store, open it once to accept the licence, and `sudo xcode-select -s /Applications/Xcode.app` if xcodebuild still says it is only the command line tools"))
            elif int(xv.split(".")[0]) < MIN_XCODE:
                problems.append(("Xcode %s is too old (devicectl needs Xcode %d or newer)" % (xv, MIN_XCODE), "update Xcode"))
            if xv and not sv:
                problems.append(("Xcode has no %s SDK" % ("iphonesimulator" if self.sim else "iphoneos"), "Xcode > Settings > Components: install the iOS platform (or `xcodebuild -downloadPlatform iOS`)"))
            if not self.sim and xv and not dv:
                problems.append(("`xcrun devicectl` is not there or does not run", "update Xcode (devicectl came with Xcode 15)"))
            if self.sim and xv and self.r.run(["xcrun", "--find", "simctl"], "read").rc != 0:
                problems.append(("`xcrun simctl` is not there", "update Xcode"))
        if problems:
            raise Fail(problems[0][0], problems[0][1])
        # where the game's code comes from
        have_prebuilt = os.path.isfile(os.path.join(self.root, "prebuilt", "iphonesimulator" if self.sim else "iphoneos", "game_magic.o"))
        self.libs, why, warning = choose_libs(self.kit, "iphonesimulator" if self.sim else "iphoneos", sv, o.rebuild, o.prebuilt, have_prebuilt)
        if self.libs == "sources" and self.kit is None and not o.data_only and not o.no_build and not os.path.isfile(os.path.join(self.root, "sources", "generated", "lift_magic_all", "handlers_gen.c")):
            raise Fail("the game has not been lifted here (sources/generated/lift_magic_all is missing)", "install and lift it first (tools/install/install.py ... --build, or tools/lift/lift_all.sh), "
                       "or use an iPad kit made on a Mac that has")
        if self.libs == "sources" and self.kit is not None and not os.path.isdir(os.path.join(self.root, "sources", "generated")):
            raise Fail("this kit has no lifted C and no prebuilt objects for this SDK")
        self.data_dir = self.find_data() if "data" in self.steps else None
        bits = []
        if xv:
            bits.append("Xcode %s (%s)" % (xv, xb))
        if sv:
            bits.append("%s SDK %s" % ("iphonesimulator" if self.sim else "iphoneos", sv))
        if dv:
            bits.append("devicectl %s" % dv)
        bits.append("game code: %s" % why)
        self.say("prerequisites", "ok: " + "; ".join(bits) if not self.r.offline else "skipped the tool checks (device list from a file); game code: %s" % why)
        if warning:
            self.warn(warning)
        if xv and xv.split(".")[0] != TESTED_XCODE.split(".")[0]:
            self.warn("only Xcode %s has built and run this (docs/notes/ios.md, \"What was tested\"); %s may work" % (TESTED_XCODE, xv))
        if self.data_dir:
            fp = fingerprint(self.data_dir)
            self.fp = fp
            self.note("game folder %s: %d files, %.0f MB" % (self.data_dir, fp[1], fp[2] / 1e6))

    def find_data(self):
        o = self.o
        if o.data:
            cands = [o.data]
        elif self.kit is not None:
            cands = [os.path.join(self.root, "Magic")]
        else:
            cands = [os.path.join(self.root, "sources", "installed", "Magic")]
        for c in cands:
            c = os.path.abspath(c)
            if os.path.isfile(os.path.join(c, "Program", "MAGIC.EXE")):
                return c
        raise Fail("the game folder is not there (looked for %s/Program/MAGIC.EXE)" % cands[0], "pass --data FOLDER (the folder that holds Program/MAGIC.EXE), or --no-data to skip the copy")

    # ---- 2: the device ----
    def choose_device(self):
        o = self.o
        want = self.setting("PENTAMOOR_DEVICE", o.device)[0]
        if o.device_json:
            with open(o.device_json) as f:
                doc = json.load(f)
            res = Result(0, "")
        else:
            res, doc = self.read_json(cmd_list_devices, "devices.json")
            if not res.ok or doc is None:
                self.fail_output(res if not res.ok else Result(1, res.out + "\nno JSON was written"), "`devicectl list devices`")
        devs = parse_devices(doc)
        if o.list_devices:
            self.out.write("Devices devicectl knows about:\n" + device_summary_table(devs) + "\n")
            raise StopDeploy()
        self.dev = pick_device(devs, want)
        errs = [p for p in device_problems(self.dev) if p[0] == "error"]
        warns = [p for p in device_problems(self.dev) if p[0] == "warn"]
        if errs:
            raise Fail("; ".join(e[1] for e in errs), "\n".join(e[2] for e in errs if e[2]))
        if not self.r.offline:
            res, doc = self.read_json(lambda p: cmd_lock_state(self.dev.ref, p), "lock.json", timeout=30)
            locked = lock_state_locked(doc) if doc else None
            if locked is True:
                raise Fail("%s is locked" % self.dev.name, "unlock the iPad (and keep it awake while this runs), then run again")
            lock = "unlocked" if locked is False else "lock state unknown"
        else:
            lock = "lock state not checked"
        self.say("device", "%s, Developer Mode %s, %s" % (self.dev.describe(), self.dev.developer_mode or "unknown", lock))
        for w in warns:
            self.warn(w[1] + (" (" + w[2] + ")" if w[2] else ""))

    def choose_simulator(self):
        res = self.r.run(cmd_sim_list(), "read", timeout=60)
        if self.r.offline and not res.out:
            raise Fail("--simulator needs Xcode; there is nothing to look at offline")
        if not res.ok:
            self.fail_output(res, "`simctl list devices`")
        sims = parse_simulators(json.loads(res.out))
        self.sim_row = pick_simulator(sims, self.o.simulator)
        udid, name, state, runtime = self.sim_row
        boot = self.r.run(cmd_sim_boot(udid), "write", timeout=300)
        if not boot.ok:
            self.fail_output(boot, "booting the Simulator")
        if self.o.open_simulator and not self.r.dry:
            subprocess.run(["open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", udid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.say("device", "Simulator %s (%s, %s), %s" % (name, runtime, udid, "was booted" if state == "Booted" else "booted now"))

    # ---- 3: signing ----
    def detect_team(self):
        """The team id from the Apple Development certificates in the keychain: (team, "how") or Fail. Only public certificates are read (security find-certificate -p, openssl x509)."""
        teams = {}
        for cn in ("Apple Development", "iPhone Developer"):
            res = self.r.run(["security", "find-certificate", "-a", "-c", cn, "-p"], "read", timeout=60)
            if not res.ok:
                continue
            for pem in split_pems(res.out):
                x = subprocess.run(["openssl", "x509", "-noout", "-subject", "-checkend", "0"], input=pem, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                if x.returncode != 0:         # expired (or unreadable)
                    continue
                subj = next((l for l in x.stdout.splitlines() if l.startswith("subject")), "")
                t = team_from_subject(subj)
                if t:
                    teams.setdefault(t, cn_from_subject(subj))
        if len(teams) == 1:
            t = list(teams)[0]
            return t, "from the Apple Development certificate \"%s\"" % teams[t]
        how = ("find your Team ID at developer.apple.com > Account > Membership details, or in Xcode > Settings > Accounts (select your Apple ID, the Team ID is next to the team), "
               "then  --team TEAMID1234  (or PENTAMOOR_TEAM=TEAMID1234 in %s, so that you never type it)" % self.config_file)
        if not teams:
            only = self.developer_id_teams()
            if only:
                raise Fail("no team given, and the only code-signing certificate found is Developer ID (team %s), which cannot sign an app for a device (it is for apps outside the App Store); "
                           "detection looks for Apple Development / iPhone Developer certificates only" % ", ".join(sorted(only)),
                           "pass that team with --team %s: xcodebuild's automatic signing makes the Apple Development certificate and profile itself if the Apple ID of the team is signed in to Xcode "
                           "(Settings > Accounts)" % sorted(only)[0])
            raise Fail("no team given and no valid Apple Development certificate was found in the keychain", how + ". (Signed in to Xcode with your Apple ID but no certificate yet? Xcode makes one on the first build "
                       "when --team is given.)")
        raise Fail("no team given and the keychain has certificates of %d teams (%s)" % (len(teams), ", ".join(sorted(teams))), how)

    def developer_id_teams(self):
        """Teams of Developer ID certificates in the keychain (only to explain that they are not what a device needs)."""
        teams = set()
        for cn in ("Developer ID Application", "Developer ID Installer"):
            res = self.r.run(["security", "find-certificate", "-a", "-c", cn, "-p"], "read", timeout=60)
            for pem in split_pems(res.out if res.ok else ""):
                x = subprocess.run(["openssl", "x509", "-noout", "-subject"], input=pem, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                t = team_from_subject(x.stdout)
                if t:
                    teams.add(t)
        return teams

    def setting(self, name, cli):
        """A setting and where it came from: the command line, else the environment, else the settings file (config_path()), else ("", "")."""
        if cli:
            return cli, "from the command line"
        if os.environ.get(name):
            return os.environ[name], "from $" + name
        if self.config.get(name):
            return self.config[name], "from " + self.config_file
        return "", ""

    def signing(self):
        o = self.o
        need_team = not self.sim and not (o.data_only or o.logs or o.no_build)
        self.bundle, bundle_from = self.setting("PENTAMOOR_BUNDLE_ID", o.bundle_id)
        if not self.bundle:
            self.bundle, bundle_from = default_bundle_id(), ""
        if not valid_bundle_id(self.bundle):
            raise Fail("\"%s\" is not a bundle id (letters, digits, dots and hyphens, with a dot: com.you.pentamoor)" % self.bundle)
        team, how = self.setting("PENTAMOOR_TEAM", o.team)
        if team:
            if not valid_team(team):
                raise Fail("the team (%s) is the 10-character Team ID (like TEAMID1234), not a name" % how, "Xcode > Settings > Accounts, or developer.apple.com > Membership details")
        elif need_team:
            if self.r.offline:
                raise Fail("--team is needed with a device list from a file")
            team, how = self.detect_team()
        self.team = "" if self.sim else team
        if self.sim:
            self.say("signing", "Simulator: no account needed; bundle id %s" % self.bundle)
        elif need_team:
            self.say("signing", "team %s (%s), bundle id %s (%s)" % (team, how, self.bundle, bundle_from or "default; change with --bundle-id"))
            self.note("xcodebuild signs automatically with the Apple ID signed in to Xcode (Settings > Accounts); it makes the profile and registers the iPad itself")
        else:
            self.say("signing", "bundle id %s (no build, so no team needed)" % self.bundle)

    # ---- 4, 5: project and build ----
    def project(self):
        xc = os.path.join(self.work, "xcode")
        prebuilt = os.path.join(self.root, "prebuilt") if self.libs == "prebuilt" else None
        c = cmd_gen_project(xc, self.team, self.bundle, self.o.entitlements, prebuilt)
        if not self.r.dry:
            os.makedirs(self.work, exist_ok=True)
        res = self.r.run(c, "write", timeout=120)
        if not res.ok:
            self.fail_output(res, "the Xcode project generator")
        self.proj = os.path.join(xc, "Pentamoor.xcodeproj")
        self.say("project", "%s (%s)" % (self.proj, "linking the prebuilt game modules" if prebuilt else "building SDL2 and the game modules from the lifted C first"))

    def build(self):
        derived = os.path.join(self.work, "derived-" + ("simulator" if self.sim else "device"))
        self.derived = derived
        if self.sim:
            dest = "platform=iOS Simulator,id=%s" % self.sim_row[0]
        else:
            dest = "platform=iOS,id=%s" % self.dev.ref
        c = cmd_build(self.proj, derived, dest, self.team, self.bundle, device=not self.sim)
        logfile = os.path.join(self.work, "xcodebuild-%s.log" % ("simulator" if self.sim else "device"))
        self.long("xcodebuild (%s; log: %s)" % ("first build: a minute or two" if not os.path.isdir(derived) else "incremental", logfile))
        t0 = time.time()
        if not self.r.dry:
            os.makedirs(self.work, exist_ok=True)
        res = self.r.run(c, "write", logfile=None if self.r.dry else logfile)
        if not res.ok:
            if not self.sim and SIGNING_FAILURE.search(res.out):
                lines = "\n".join(error_lines(res.out))
                hints = [h for h in explain(res.out) if "Settings > Accounts" not in h]
                raise Fail("xcodebuild could not create a provisioning profile for team %s:\n%s" % (self.team, lines),
                           "add/sign in your Apple ID in Xcode > Settings > Accounts (the account that owns team %s), then re-run. The whole log is %s.%s" % (self.team, logfile, ("\n" + "\n".join(hints)) if hints else ""))
            self.fail_output(res, "xcodebuild")
        self.app = built_app_path(derived, device=not self.sim)
        if not self.r.dry and not os.path.isdir(self.app):
            raise Fail("xcodebuild finished but %s is not there" % self.app, "see %s" % logfile)
        self.say("build", "%s%s" % (self.app, "" if self.r.dry else " (%d s)" % (time.time() - t0)))

    def find_built_app(self):
        derived = os.path.join(self.work, "derived-" + ("simulator" if self.sim else "device"))
        self.app = built_app_path(derived, device=not self.sim)
        if not self.r.dry and not os.path.isdir(self.app):
            raise Fail("--no-build: there is no earlier build (%s)" % self.app, "run once without --no-build")

    # ---- 6: install ----
    def install(self):
        if self.sim:
            res = self.r.run(cmd_sim_install(self.sim_row[0], self.app), "write", timeout=300)
        else:
            res = self.r.run(cmd_install(self.dev.ref, self.app), "write", stream=False, timeout=600)
        if not res.ok:
            self.fail_output(res, "installing the app")
        self.say("install", "%s on %s" % (self.bundle, self.sim_row[1] if self.sim else self.dev.name))

    # ---- 7: data ----
    def sim_documents(self):
        res = self.r.run(cmd_sim_container(self.sim_row[0], self.bundle), "read", timeout=60)
        if not res.ok and not self.r.dry:
            self.fail_output(res, "finding the app's data folder (is it installed?)")
        return os.path.join(res.out.strip(), "Documents") if res.ok and res.out.strip() else "<the app's data folder>/Documents"

    def remote_text(self, source, name):
        """The text of a file in the app's container on the iPad, or None (not there, or not readable)."""
        dst = self.tmpfile(name)
        if os.path.exists(dst):
            shutil.rmtree(dst) if os.path.isdir(dst) else os.remove(dst)
        res = self.r.run(cmd_copy_from(self.dev.ref, self.bundle, source, dst), "read", timeout=120)
        if not res.ok:
            return None
        cand = [dst, os.path.join(dst, os.path.basename(source))]
        for c in cand:
            if os.path.isfile(c):
                with open(c, errors="replace") as f:
                    return f.read()
        return None

    def remote_listing(self, subdir, name="files.json"):
        """The raw text of `devicectl device info files` for a folder in the container, or None if the command failed (the folder is not there, or the listing is not available)."""
        path = self.tmpfile(name)
        if os.path.exists(path):
            os.remove(path)
        res = self.r.run(cmd_files(self.dev.ref, self.bundle, subdir, path), "read", timeout=120)
        if not res.ok:
            return None
        text = res.out
        if os.path.isfile(path):
            with open(path, errors="replace") as f:
                text += f.read()
        return text

    def push_file(self, local, remote):
        res = self.r.run(cmd_copy_to(self.dev.ref, self.bundle, local, remote), "write", timeout=600)
        if not res.ok:
            self.fail_output(res, "copying %s to the iPad" % os.path.basename(local))

    def copy_layout(self):
        """How does `devicectl device copy to --source DIR --destination D` place a directory: as D itself ("target") or inside D ("parent")? Its help does not say, so a one-file folder is
        copied first and looked for. Returns "target", "parent", or "unknown" (the listing is not usable; "target" is then assumed and the result is checked after the copy)."""
        d = self.tmpfile("probe-src")
        os.makedirs(os.path.join(d, "x"), exist_ok=True)
        with open(os.path.join(d, "x", "probe.txt"), "w") as f:
            f.write("pentamoor probe\n")
        self.push_file(d, PROBE_DIR)
        if self.r.dry:
            return "target"
        as_target = self.remote_listing(PROBE_DIR + "/x", "probe-a.json")
        inside = self.remote_listing(PROBE_DIR + "/probe-src/x", "probe-b.json")
        a = bool(as_target and "probe.txt" in as_target)
        b = bool(inside and "probe.txt" in inside)
        if a and not b:
            return "target"
        if b and not a:
            return "parent"
        return "unknown"

    def data(self):
        o = self.o
        fp = self.fp
        if self.sim:
            return self.data_sim(fp)
        stamp = self.remote_text(STAMP_FILE, "remote.stamp")
        if stamp is not None and stamp_id(stamp) == fp[0] and not o.force_data:
            have = self.remote_listing(DATA_DIR + "/Program", "game.json")
            # a failed listing means "the folder is gone" if Documents itself can be listed, and "listing is not available here" if it cannot (then the stamp is trusted)
            if (have is None and self.remote_listing("Documents", "docs.json") is None) or (have is not None and "MAGIC.EXE" in have.upper()):
                self.say("data", "already on the iPad (%d files, %.0f MB, same stamp), not copied (--force-data copies again)" % (fp[1], fp[2] / 1e6))
                self.program_txt()
                return
            self.warn("the stamp matches but %s/Program/MAGIC.EXE is gone from the app: copying again" % DATA_DIR)
        self.long("copying %d files, %.0f MB to %s on the iPad (USB: a minute or two; Wi-Fi: longer)" % (fp[1], fp[2] / 1e6, DATA_DIR))
        self.layout = self.copy_layout()
        dest = DATA_DIR if self.layout in ("target", "unknown") else os.path.dirname(DATA_DIR)
        if self.layout == "parent" and os.path.basename(self.data_dir) != "Magic":
            raise Fail("devicectl copies a folder into the destination, keeping its name, so the game folder must be called Magic (it is %s)" % os.path.basename(self.data_dir),
                       "pass --data with a folder called Magic")
        self.push_file(self.data_dir, dest)
        check = self.remote_listing(DATA_DIR + "/Program", "game.json")
        if self.r.dry:
            pass
        elif check is None:
            self.warn("could not list Documents/Magic/Program on the iPad to check the copy (`devicectl device info files`); the app will say if it cannot find the game")
        elif "MAGIC.EXE" not in check.upper():
            nested = self.remote_listing(DATA_DIR + "/Magic/Program", "game2.json")
            raise Fail("the copy is not where the app looks: Documents/Magic/Program/MAGIC.EXE is not on the iPad" + (" (it is in Documents/Magic/Magic/: devicectl nested the folder)" if nested and "MAGIC.EXE" in nested.upper() else ""),
                       "open an issue with `xcrun devicectl device info files --device %s --domain-type appDataContainer --domain-identifier %s` attached; as a workaround copy the folder with Finder (the iPad > Files > Pentamoor)" % (self.dev.ref, self.bundle))
        local = self.tmpfile("pentamoor-data.stamp")
        with open(local, "w") as f:
            f.write(make_stamp(fp))
        self.push_file(local, STAMP_FILE)
        self.program_txt()
        self.say("data", "copied %d files (%.0f MB) to Documents/Magic%s" % (fp[1], fp[2] / 1e6, " (verified)" if check and not self.r.dry else ""))

    def program_txt(self):
        if self.o.program and not self.sim:
            p = self.tmpfile("program.txt")
            with open(p, "w") as f:
                f.write(self.o.program + "\n")
            self.push_file(p, PROGRAM_FILE)
            self.note("program: %s (Documents/program.txt)" % self.o.program)

    def data_sim(self, fp):
        docs = self.sim_documents()
        stamp_path = os.path.join(docs, os.path.basename(STAMP_FILE))
        magic = os.path.join(docs, "Magic")
        have = None
        if os.path.isfile(stamp_path):
            with open(stamp_path) as f:
                have = stamp_id(f.read())
        if have == fp[0] and os.path.isfile(os.path.join(magic, "Program", "MAGIC.EXE")) and not self.o.force_data:
            self.say("data", "already in the Simulator's app (%d files, %.0f MB, same stamp), not copied" % (fp[1], fp[2] / 1e6))
        else:
            self.long("copying %d files, %.0f MB into the Simulator's app" % (fp[1], fp[2] / 1e6))
            if self.r.dry:
                self.r.show(["cp", "-R", self.data_dir, magic], prefix="  would run:")
            else:
                os.makedirs(docs, exist_ok=True)
                if os.path.isdir(magic):
                    if not magic.endswith("/Documents/Magic"):
                        raise Fail("refusing to replace %s" % magic)
                    shutil.rmtree(magic)
                subprocess.run(["cp", "-R", self.data_dir, magic], check=True)
                with open(stamp_path, "w") as f:
                    f.write(make_stamp(fp))
            self.say("data", "copied %d files (%.0f MB) to %s" % (fp[1], fp[2] / 1e6, magic))
        if self.o.program and not self.r.dry:
            with open(os.path.join(docs, "program.txt"), "w") as f:
                f.write(self.o.program + "\n")
            self.note("program: %s" % self.o.program)

    # ---- 8: launch ----
    def launch(self):
        env = {}
        if self.o.console:
            env[("SIMCTL_CHILD_" if self.sim else "DEVICECTL_CHILD_") + "PENTAMOOR_LOG"] = "console"
        c = cmd_sim_launch(self.sim_row[0], self.bundle, self.o.console) if self.sim else cmd_launch(self.dev.ref, self.bundle, self.o.console)
        res = self.r.run(c, "write", env=env or None, stream=self.o.console, timeout=None if self.o.console else 120)
        if not res.ok:
            if not self.o.console:
                self.fail_output(res, "starting the app")
            self.warn("the app ended (exit %d)" % res.rc)
        self.say("launch", "%s%s" % (self.bundle, " (output follows)" if self.o.console else ""))

    # ---- logs ----
    def logs(self):
        out = os.path.abspath(self.o.logs_out or os.path.join(self.work, "pentamoor-%s.log" % ("simulator" if self.sim else "ipad")))
        if self.sim:
            src = os.path.join(self.sim_documents(), "pentamoor.log")
            if self.r.dry:
                self.r.show(["cp", src, out], prefix="  would run:")
                text = ""
            elif not os.path.isfile(src):
                raise Fail("the app has not written a log yet (%s)" % src)
            else:
                os.makedirs(os.path.dirname(out), exist_ok=True)
                shutil.copyfile(src, out)
                text = open(out, errors="replace").read()
        else:
            if not self.r.dry:
                os.makedirs(os.path.dirname(out), exist_ok=True)
            res = self.r.run(cmd_copy_from(self.dev.ref, self.bundle, LOG_FILE, out), "write", timeout=120)
            if not res.ok:
                self.fail_output(res, "copying Documents/pentamoor.log from the iPad")
            text = open(out, errors="replace").read() if not self.r.dry and os.path.isfile(out) else ""
        self.say("logs", "saved to %s (%d lines)" % (out, len(text.splitlines())))
        if text:
            self.out.write("".join("        | %s\n" % l for l in text.splitlines()[-40:]))

    # ---- the whole run ----
    def plan(self):
        o = self.o
        if o.logs:
            return ["prerequisites", "device", "signing", "logs"]
        steps = ["prerequisites", "device", "signing"]
        if o.data_only:
            return steps + ["data"]
        if not o.no_build:
            steps += ["project", "build"]
        else:
            pass
        steps += ["install"] if not o.no_install else []
        if not o.no_data:
            steps += ["data"]
        if not o.no_launch:
            steps += ["launch"]
        return steps

    def run(self):
        o = self.o
        self.steps = self.plan()
        self.out.write("Pentamoor deploy: %s%s\n" % ("Simulator" if self.sim else "iPad", "  (dry run: nothing is changed, the commands are only printed)" if o.dry_run else ""))
        try:
            for s in self.steps:
                if s == "prerequisites":
                    self.prerequisites()
                elif s == "device":
                    self.choose_simulator() if self.sim else self.choose_device()
                elif s == "signing":
                    self.signing()
                elif s == "project":
                    self.project()
                elif s == "build":
                    self.build()
                elif s == "install":
                    if not hasattr(self, "app"):
                        self.find_built_app()
                    self.install()
                elif s == "data":
                    self.data()
                elif s == "launch":
                    self.launch()
                elif s == "logs":
                    self.logs()
        finally:
            if self.tmp:
                shutil.rmtree(self.tmp, ignore_errors=True)
        self.finish()

    def finish(self):
        o = self.o
        self.out.write("\n")
        if o.dry_run:
            self.out.write("Dry run done: nothing was changed.\n")
            return
        if o.logs:
            return
        if self.sim:
            self.out.write("Done.%s\n" % (" The app is running in the Simulator." if "launch" in self.steps else ""))
            return
        self.out.write("Done.%s\n" % (" Pentamoor should be starting on the iPad." if "launch" in self.steps else ""))
        self.out.write("If the iPad says \"Untrusted Developer\" (or the app closes at once): Settings > General > VPN & Device Management > your Apple ID under Developer App > Trust, then open Pentamoor.\n"
                       "A development build lasts as long as its profile: a year with a paid developer account, 7 days with a free one; run this again to renew it (the game is not copied twice).\n"
                       "If something is wrong: deploy.sh --logs brings Pentamoor's log (Documents/pentamoor.log) from the iPad; docs/notes/ios.md has the usual errors.\n")


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------
# --selftest
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def help_command(tool):
    if tool == ("xcodebuild",):
        return ["xcodebuild", "-help"]
    if tool[:2] == ("xcrun", "simctl"):
        return ["xcrun", "simctl", "help", tool[2]]
    return list(tool) + ["--help"]


def flag_in_help(flag, text):
    return bool(re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", text))


def selftest(out=sys.stdout):
    """Run each tool's own help and check that every option this script passes is in it, then read the real device list with the parser. Returns the number of problems."""
    bad = 0
    for tool, flags in sorted(TOOL_FLAGS.items()):
        res = subprocess.run(help_command(tool), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, errors="replace")
        missing = [f for f in flags if not flag_in_help(f, res.stdout)]
        if res.returncode != 0 and not res.stdout.strip():
            out.write("FAIL %-52s the help does not run (exit %d)\n" % (" ".join(tool), res.returncode))
            bad += 1
        elif missing:
            out.write("FAIL %-52s not in its help: %s\n" % (" ".join(tool), " ".join(missing)))
            bad += 1
        else:
            out.write("ok   %-52s %s\n" % (" ".join(tool), " ".join(flags) or "(no options)"))
    tmp = tempfile.mkdtemp(prefix="pentamoor-selftest-")
    try:
        p = os.path.join(tmp, "devices.json")
        res = subprocess.run(cmd_list_devices(p), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        if res.returncode != 0 or not os.path.isfile(p):
            out.write("FAIL `devicectl list devices` did not run: %s\n" % res.stdout.strip()[-200:])
            bad += 1
        else:
            devs = parse_devices(json.load(open(p)))
            real = [d for d in devs if not d.is_simulator]
            out.write("ok   devicectl list devices: %d devices parsed (%d real, %d simulated); iPads: %s\n" % (len(devs), len(real), len(devs) - len(real),
                      ", ".join(d.name for d in real if d.is_ipad) or "none connected"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out.write("selftest: %s\n" % ("all options exist in this Xcode" if not bad else "%d problem(s)" % bad))
    return bad


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def make_parser():
    ap = argparse.ArgumentParser(prog="deploy.sh", description="Put Pentamoor on an iPad (or in the Simulator): build, sign, install, copy the game in, start it.",
                                 epilog="Examples:  deploy.sh --team ABCDE12345     deploy.sh --dry-run --team ABCDE12345     deploy.sh --logs     deploy.sh --simulator \"Pentamoor iPad Pro\"")
    t = ap.add_argument_group("where to")
    t.add_argument("--device", metavar="ID", help="the iPad: its name, UDID, serial number, ECID or CoreDevice id (default: the only iPad that is connected; $PENTAMOOR_DEVICE)")
    t.add_argument("--simulator", nargs="?", const="auto", metavar="UDID|NAME", help="use an iOS Simulator instead (no account, no device): xcodebuild and simctl, the same steps")
    s = ap.add_argument_group("signing")
    s.add_argument("--team", metavar="TEAMID", help="your 10-character Apple developer Team ID ($PENTAMOOR_TEAM or the settings file ~/.config/pentamoor/ios.env; default: the team of the one Apple Development certificate in your keychain)")
    s.add_argument("--bundle-id", metavar="ID", help="the app's identifier, one that no other team uses ($PENTAMOOR_BUNDLE_ID or the settings file; default com.<your user name>.pentamoor)")
    s.add_argument("--entitlements", action="store_true", help="sign with tools/ios/Pentamoor.entitlements (more address space and memory; see docs/notes/ios.md, Memory)")
    g = ap.add_argument_group("what to do")
    g.add_argument("--data", metavar="FOLDER", help="the game folder, the one that holds Program/MAGIC.EXE (default: Magic/ in a kit, else sources/installed/Magic)")
    g.add_argument("--no-data", action="store_true", help="do not copy the game")
    g.add_argument("--data-only", action="store_true", help="only copy the game (and --program) to the app already on the iPad")
    g.add_argument("--force-data", action="store_true", help="copy the game even when the same data is already there")
    g.add_argument("--program", choices=("magic", "deck", "duel"), help="which program the app runs (writes Documents/program.txt; default magic)")
    g.add_argument("--no-build", action="store_true", help="install the app built last time")
    g.add_argument("--no-install", action="store_true", help="build only")
    g.add_argument("--no-launch", action="store_true", help="do not start the app")
    g.add_argument("--console", action="store_true", help="start the app and follow its output (Ctrl-C to stop); the app logs to the console instead of Documents/pentamoor.log")
    g.add_argument("--logs", action="store_true", help="bring Documents/pentamoor.log from the app (to --logs-out, default in the work folder) and show its end; nothing else")
    g.add_argument("--logs-out", metavar="FILE", help=argparse.SUPPRESS)
    k = ap.add_argument_group("the game's code")
    k.add_argument("--rebuild", action="store_true", help="in a kit with lifted C (--with-sources): compile it instead of linking the prebuilt objects")
    k.add_argument("--prebuilt", action="store_true", help="in a kit: link the prebuilt objects even when this Xcode's SDK is not the one they were built with")
    o = ap.add_argument_group("other")
    o.add_argument("--dry-run", action="store_true", help="print the commands that change something instead of running them (the ones that only look still run)")
    o.add_argument("--device-json", metavar="FILE", help="use this saved `devicectl list devices --json-output` instead of asking; runs nothing at all (for --dry-run and tests)")
    o.add_argument("--list-devices", action="store_true", help="show the devices devicectl knows about and stop")
    o.add_argument("--selftest", action="store_true", help="check that every xcodebuild, devicectl and simctl option used here exists in this Xcode, and that the device list parses")
    o.add_argument("--work", metavar="DIR", help="where the Xcode project, the build and the logs go (default dist/ios/deploy)")
    o.add_argument("--open-simulator", action="store_true", help=argparse.SUPPRESS)
    o.add_argument("-v", "--verbose", action="store_true", help="show every command")
    return ap


def main(argv=None):
    opts = make_parser().parse_args(argv)
    if opts.selftest:
        return 1 if selftest() else 0
    if opts.device_json:
        opts.dry_run = True
    if opts.data_only and (opts.no_data or opts.logs):
        print("deploy: --data-only goes with neither --no-data nor --logs", file=sys.stderr)
        return 2
    if opts.simulator is not None and opts.device:
        print("deploy: --device and --simulator are two answers to one question", file=sys.stderr)
        return 2
    try:
        Deployer(opts).run()
    except Fail as e:
        sys.stdout.flush()
        print("\ndeploy: %s" % e, file=sys.stderr)
        if e.hint:
            print("\n%s" % e.hint, file=sys.stderr)
        return 1
    except StopDeploy:
        return 0
    except KeyboardInterrupt:
        print("\ndeploy: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
