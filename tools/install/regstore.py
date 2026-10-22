"""
regstore.py - the installer's side of the file registry (src/port/regstore.c, regstore.h): a text file in an install's overlay that holds the few registry values a Spells of the
Ancients 2.15 run reads and writes.

The file (docs/notes/sota-licence.md, "The registry file"): a first line "# pentamoor registry 1", then one value a line, `key TAB name TAB type TAB hex`, the key a path from the root
("HKLM\\SOFTWARE\\..."), the type the registry's number (1 string, 3 binary, 4 DWORD), the bytes in lower-case hex. Only values under HKLM\\SOFTWARE\\MicroProse and HKCU\\SOFTWARE\\MicroProse and the two Windows
values FirstInstallDateTime and ProductId are kept; the runtime drops any other line. This module reads and writes that format, the same way the runtime does, and makes the install's own
machine pair: a random install time and a random product id, made once, when the install is made. It holds nothing about what any program stores in the other values.

This module makes no licence value and knows nothing about how one is made. The pair it creates is two random numbers of the shape Windows 98 gave.
"""
import datetime
import os
import secrets

HEADER = "# pentamoor registry 1"
WINDOWS_KEY = "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion"
MICROPROSE_KEY = "HKLM\\SOFTWARE\\MicroProse"
USER_KEY = "HKCU\\SOFTWARE\\MicroProse"                # the Magic Shell's page settings (the runtime keeps them: regstore.h)
LICENCE_KEY = MICROPROSE_KEY + "\\Magic: The Gathering"
INSTALL_TIME = "FirstInstallDateTime"
PRODUCT_ID = "ProductId"
REG_SZ, REG_BINARY, REG_DWORD = 1, 3, 4
MAX_VALUES = 128
MAX_DATA = 1024


class RegError(Exception):
    pass


def keeps(key, name=None):
    """Does the store keep this value (the runtime's regstore_keeps)?"""
    k = key.lower()
    for mp in (MICROPROSE_KEY.lower(), USER_KEY.lower()):
        if k == mp or k.startswith(mp + "\\"):
            return True
    if k == WINDOWS_KEY.lower():
        return name is None or name.lower() in (INSTALL_TIME.lower(), PRODUCT_ID.lower())
    return False


def _clean(text, cap):
    return 0 < len(text) < cap and not any(c in text for c in "\t\r\n")


class Store:
    """The values of one registry file. Reading never raises (a file that is not there is an empty store; a line the runtime would drop is dropped); writing raises RegError."""

    def __init__(self, path):
        self.path = path
        self.values = {}                     # (key.lower(), name.lower()) -> (key, name, type, bytes)
        self.dropped = 0
        self._read()

    def _read(self):
        try:
            with open(self.path, "rb") as f:
                raw = f.read()
        except OSError:
            return
        for line in raw.decode("latin-1").split("\n"):
            line = line.rstrip("\r")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 4 or not parts[2].isdigit() or not _clean(parts[0], 300) or not _clean(parts[1], 100) or not keeps(parts[0], parts[1]):
                self.dropped += 1
                continue
            try:
                data = bytes.fromhex(parts[3])
            except ValueError:
                self.dropped += 1
                continue
            if len(data) > MAX_DATA:
                self.dropped += 1
                continue
            if (parts[0].lower(), parts[1].lower()) not in self.values and len(self.values) >= MAX_VALUES:
                self.dropped += 1
                continue
            self.values[(parts[0].lower(), parts[1].lower())] = (parts[0], parts[1], int(parts[2]), data)

    def get(self, key, name):
        """(type, bytes) or None."""
        v = self.values.get((key.lower(), name.lower()))
        return (v[2], v[3]) if v else None

    def put(self, key, name, typ, data):
        """Set a value and write the file (a temporary file, then a rename). Raises RegError for a value the store does not keep."""
        if not keeps(key, name) or not _clean(key, 300) or not _clean(name, 100) or len(data) > MAX_DATA:
            raise RegError(f"the registry file does not keep {key}\\{name}")
        if (key.lower(), name.lower()) not in self.values and len(self.values) >= MAX_VALUES:
            raise RegError("the registry file is full")
        self.values[(key.lower(), name.lower())] = (key, name, int(typ), bytes(data))
        self.save()

    def remove(self, key, name):
        if self.values.pop((key.lower(), name.lower()), None) is not None:
            self.save()

    def lines(self):
        out = [HEADER]
        for key, name, typ, data in self.values.values():
            out.append(f"{key}\t{name}\t{typ}\t{data.hex()}")
        return "\n".join(out) + "\n"

    def save(self):
        folder = os.path.dirname(os.path.abspath(self.path))
        try:
            os.makedirs(folder, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(self.lines().encode("latin-1"))
            os.replace(tmp, self.path)
        except OSError as e:
            raise RegError(f"cannot write {self.path}: {e}") from e


# ---- this install's machine pair ---------------------------------------------------------------------------------------------------------------------------------
def make_pair(rng=None):
    """A new pair, (install time as 4 bytes, product id as the 24 bytes of a string with its NUL): random numbers shaped like Windows 98's (an install date in 1998 to 2000, and
    ddddd-OEM-ddddddd-ddddd). `rng` is a random.Random for the tests; the installer uses the system's source."""
    if rng is None:
        below = secrets.randbelow
    else:
        def below(n):
            return rng.randrange(n)
    lo = int(datetime.datetime(1998, 6, 1, tzinfo=datetime.timezone.utc).timestamp())
    hi = int(datetime.datetime(2000, 12, 31, tzinfo=datetime.timezone.utc).timestamp())
    when = lo + below(hi - lo)
    digits = lambda n: "".join(str(below(10)) for _ in range(n))       # noqa: E731
    pid = f"{digits(5)}-OEM-{digits(7)}-{digits(5)}"
    return when.to_bytes(4, "little"), pid.encode("ascii") + b"\0"


def has_pair(store):
    return store.get(WINDOWS_KEY, INSTALL_TIME) is not None and store.get(WINDOWS_KEY, PRODUCT_ID) is not None


def ensure_pair(path, rng=None):
    """Make sure the registry file at `path` holds this install's own machine pair. Returns True when it made one now, False when there was one (it is never replaced: a value written
    for a pair is only good with that pair). Raises RegError if the file cannot be written."""
    store = Store(path)
    if has_pair(store):
        return False
    when, pid = make_pair(rng)
    store.put(WINDOWS_KEY, INSTALL_TIME, REG_BINARY, when)
    store.put(WINDOWS_KEY, PRODUCT_ID, REG_SZ, pid)
    return True
