"""The C runtime (msvcrtd.dll) as Python: strings, memory, stdio and low-level files, time, ctype."""
import io
import os
import struct
import time as _time

from unicorn.x86_const import UC_X86_REG_ESP

from .cformat import VaReader, format_c, scan_c
from .machine import Cont, ExitProcess, crt, u32
from .paths import host_path, normalize

S32 = lambda v: v - 0x100000000 if v & 0x80000000 else v


def va(m, k):
    """A reader over the varargs that follow the first k fixed arguments of the current cdecl call."""
    return VaReader(m, m.uc.reg_read(UC_X86_REG_ESP) + 4 + 4 * k)


def _state(m):
    st = m.state.setdefault("crt", {})
    if not st:
        st.update(files={}, fds={}, next_fd=3, seed=1, t0=_time.time(), errno=m.alloc(4), ctype=None,
                  mb_cur_max=m.alloc(4), fmode=m.alloc(4), commode=m.alloc(4), pctype_cell=m.alloc(4))
        m.w32(st["mb_cur_max"], 1)
    return st


def init_argv(m, argv0):
    st = _state(m)
    p = m.alloc_cstr(argv0.encode())
    arr = m.alloc(8)
    m.w32(arr, p)
    st.update(argv0=p, argv=m.alloc(4), argc=m.alloc(4), environ=m.alloc(4), acmdln=m.alloc(4))
    m.w32(st["argv"], arr)
    m.w32(st["argc"], 1)
    m.w32(st["environ"], m.alloc(8))
    m.w32(st["acmdln"], p)


# ---- start-up -------------------------------------------------------------------------------------
crt("__set_app_type")(lambda m, a: 0)
crt("_controlfp")(lambda m, a: 0x9001F)
crt("_adjust_fdiv")(lambda m, a: 0)
crt("__setusermatherr")(lambda m, a: 0)
crt("_XcptFilter")(lambda m, a: 0)
crt("_except_handler3")(lambda m, a: 1)
crt("__p__fmode")(lambda m, a: _state(m)["fmode"])
crt("__p__commode")(lambda m, a: _state(m)["commode"])
crt("__p___argv")(lambda m, a: _state(m)["argv"])
crt("__p__acmdln")(lambda m, a: _state(m)["acmdln"])
crt("__p___mb_cur_max")(lambda m, a: _state(m)["mb_cur_max"])
crt("_errno")(lambda m, a: _state(m)["errno"])


@crt("__getmainargs")
def getmainargs(m, a):
    st = _state(m)
    m.w32(a[0], 1)
    m.w32(a[1], m.r32(st["argv"]))
    m.w32(a[2], m.r32(st["environ"]))
    return 0


@crt("_initterm")
def initterm(m, a):
    """Call each nonzero function pointer in [begin, end): a chain of guest calls."""
    begin, end = a[0], a[1]

    def step(p):
        while p < end and m.r32(p) == 0:
            p += 4
        if p >= end:
            return 0
        return Cont(m.r32(p), [], lambda r: step(p + 4))
    return step(begin)


@crt("exit")
def _exit(m, a):
    raise ExitProcess(a[0])


crt("_exit")(_exit)
crt("_onexit")(lambda m, a: a[0])
crt("__dllonexit")(lambda m, a: a[0])


@crt("_assert")
def _assert(m, a):
    m.log(f"!! assertion failed: {m.cstr(a[0])!r} {m.cstr(a[1])!r} line {a[2]}")
    raise ExitProcess(3)


# ---- memory ---------------------------------------------------------------------------------------
crt("malloc")(lambda m, a: m.alloc(a[0], zero=False))
crt("_malloc_dbg")(lambda m, a: m.alloc(a[0], zero=False))
crt("calloc")(lambda m, a: m.alloc(a[0] * a[1]))
crt("_calloc_dbg")(lambda m, a: m.alloc(a[0] * a[1]))
crt("_free_dbg")(lambda m, a: m.heap.release(a[0]) or 0)


def _realloc(m, p, n):
    q = m.alloc(n, zero=False)
    if p:
        old = min(m.heap.size(p), n)
        if old:
            m.wr(q, m.rd(p, old))
        m.heap.release(p)
    return q


crt("realloc")(lambda m, a: _realloc(m, a[0], a[1]))
crt("_realloc_dbg")(lambda m, a: _realloc(m, a[0], a[1]))
crt("free")(lambda m, a: m.heap.release(a[0]) or 0)
crt("??2@YAPAXI@Z")(lambda m, a: m.alloc(a[0], zero=False))                       # operator new(size_t), the DLLs' C++ new (STATWIN.DLL's DllMain needs it)
crt("??2@YAPAXIHPBDH@Z")(lambda m, a: m.alloc(a[0], zero=False))                  # the debug form: (size, block type, file, line)
crt("??3@YAXPAX@Z")(lambda m, a: m.heap.release(a[0]) or 0)                       # operator delete(void *)
crt("_msize")(lambda m, a: m.heap.size(a[0]))
crt("_expand")(lambda m, a: a[0] if a[1] <= m.heap.size(a[0]) else 0)
crt("memcpy")(lambda m, a: (m.wr(a[0], m.rd(a[1], a[2])) if a[2] else None, a[0])[1])
crt("memmove")(lambda m, a: (m.wr(a[0], m.rd(a[1], a[2])) if a[2] else None, a[0])[1])
crt("memset")(lambda m, a: (m.wr(a[0], bytes([a[1] & 0xFF]) * a[2]) if a[2] else None, a[0])[1])


@crt("memcmp")
def memcmp(m, a):
    x, y = m.rd(a[0], a[2]), m.rd(a[1], a[2])
    return u32((x > y) - (x < y))


@crt("memchr")
def memchr(m, a):
    i = m.rd(a[0], a[2]).find(bytes([a[1] & 0xFF]))
    return 0 if i < 0 else a[0] + i


# ---- strings --------------------------------------------------------------------------------------
def _cmp(x, y):
    return u32((x > y) - (x < y))


crt("strlen")(lambda m, a: len(m.cstr(a[0])))
crt("strcpy")(lambda m, a: (m.put_cstr(a[0], m.cstr(a[1])), a[0])[1])
crt("strcat")(lambda m, a: (m.put_cstr(a[0] + len(m.cstr(a[0])), m.cstr(a[1])), a[0])[1])
crt("strcmp")(lambda m, a: _cmp(m.cstr(a[0]), m.cstr(a[1])))
crt("_stricmp")(lambda m, a: _cmp(m.cstr(a[0]).lower(), m.cstr(a[1]).lower()))
crt("_strcmpi")(lambda m, a: _cmp(m.cstr(a[0]).lower(), m.cstr(a[1]).lower()))
crt("_strnicmp")(lambda m, a: _cmp(m.cstr(a[0]).lower()[:a[2]], m.cstr(a[1]).lower()[:a[2]]))
crt("strncmp")(lambda m, a: _cmp(m.cstr(a[0])[:a[2]], m.cstr(a[1])[:a[2]]))
crt("_strlwr")(lambda m, a: (m.put_cstr(a[0], m.cstr(a[0]).lower()), a[0])[1])
crt("tolower")(lambda m, a: (a[0] + 32) if 65 <= a[0] <= 90 else a[0])
crt("abs")(lambda m, a: u32(abs(S32(a[0]))))
crt("atoi")(lambda m, a: u32(_atoi(m.cstr(a[0]))))


def _atoi(b):
    b = b.lstrip()
    i = 0
    if b[:1] in (b"+", b"-"):
        i = 1
    while i < len(b) and b[i:i + 1].isdigit():
        i += 1
    try:
        return int(b[:i])
    except ValueError:
        return 0


@crt("strncpy")
def strncpy(m, a):
    s = m.cstr(a[1])[:a[2]]
    m.wr(a[0], s.ljust(a[2], b"\0"))
    return a[0]


@crt("strncat")
def strncat(m, a):
    m.put_cstr(a[0] + len(m.cstr(a[0])), m.cstr(a[1])[:a[2]])
    return a[0]


@crt("strchr")
def strchr(m, a):
    s = m.cstr(a[0]) + b"\0"
    i = s.find(bytes([a[1] & 0xFF]))
    return 0 if i < 0 else a[0] + i


@crt("strrchr")
def strrchr(m, a):
    s = m.cstr(a[0]) + b"\0"
    i = s.rfind(bytes([a[1] & 0xFF]))
    return 0 if i < 0 else a[0] + i


@crt("strspn")
def strspn(m, a):
    s, acc, n = m.cstr(a[0]), m.cstr(a[1]), 0
    while n < len(s) and s[n] in acc:
        n += 1
    return n


@crt("strcspn")
def strcspn(m, a):
    s, rej, n = m.cstr(a[0]), m.cstr(a[1]), 0
    while n < len(s) and s[n] not in rej:
        n += 1
    return n


@crt("_itoa")
def itoa(m, a):
    v, radix = S32(a[0]), a[2]
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    n, out = abs(v), ""
    while True:
        out = digits[n % radix] + out
        n //= radix
        if not n:
            break
    m.put_cstr(a[1], (("-" if v < 0 and radix == 10 else "") + out).encode())
    return a[1]


@crt("_splitpath")
def splitpath(m, a):
    p = m.cstr(a[0]).decode("latin-1")
    drive = p[:2] if p[1:2] == ":" else ""
    rest = p[len(drive):]
    cut = max(rest.rfind("\\"), rest.rfind("/")) + 1
    d, f = rest[:cut], rest[cut:]
    dot = f.rfind(".")
    name, ext = (f[:dot], f[dot:]) if dot >= 0 else (f, "")
    for ptr, val in zip(a[1:5], (drive, d, name, ext)):
        if ptr:
            m.put_cstr(ptr, val.encode("latin-1"))
    return 0


@crt("bsearch")
def bsearch(m, a):
    key, base, num, width, cmpfn = a[:5]

    def step(lo, hi):
        if lo >= hi:
            return 0
        mid = (lo + hi) // 2
        elem = base + mid * width
        def then(r):
            r = S32(r)
            if r == 0:
                return elem
            return step(lo, mid) if r < 0 else step(mid + 1, hi)
        return Cont(cmpfn, [key, elem], then)
    return step(0, num)


# ---- ctype ----------------------------------------------------------------------------------------
def _ctype_table(m):
    st = _state(m)
    if st["ctype"] is None:
        t = bytearray()
        for c in range(-1, 256):
            f = 0
            ch = c if c >= 0 else 0
            if 65 <= ch <= 90:
                f = 0x101 | (0x80 if ch <= 70 else 0)
            elif 97 <= ch <= 122:
                f = 0x102 | (0x80 if ch <= 102 else 0)
            elif 48 <= ch <= 57:
                f = 0x84
            elif ch in (9, 10, 11, 12, 13):
                f = 0x28 | (0x40 if ch == 9 else 0)
            elif ch == 32:
                f = 0x48
            elif 33 <= ch <= 126:
                f = 0x10
            elif ch < 32 or ch == 127:
                f = 0x20
            t += struct.pack("<H", f)
        base = m.alloc(len(t))
        m.wr(base, bytes(t))
        st["ctype"] = base + 2                          # pctype[-1] is valid, so point past the first entry
        m.w32(st["pctype_cell"], st["ctype"])
    return st


crt("__p__pctype")(lambda m, a: _ctype_table(m)["pctype_cell"])


@crt("_isctype")
def isctype(m, a):
    t = _ctype_table(m)["ctype"]
    c = S32(a[0])
    if not -1 <= c <= 255:
        return 0
    return struct.unpack("<H", m.rd(t + 2 * c, 2))[0] & a[1]


# ---- printf family ----------------------------------------------------------------------------------
@crt("sprintf")
def sprintf(m, a):
    out = format_c(m, m.cstr(a[1]), va(m, 2))
    m.put_cstr(a[0], out)
    return len(out)


@crt("_vsnprintf")
def vsnprintf(m, a):
    out = format_c(m, m.cstr(a[2]), VaReader(m, a[3]))
    n = a[1]
    m.wr(a[0], out[:n] + (b"\0" if len(out) < n else b""))
    return len(out) if len(out) <= n else 0xFFFFFFFF


@crt("fprintf")
def fprintf(m, a):
    out = format_c(m, m.cstr(a[1]), va(m, 2))
    return _write_file(m, a[0], out)


@crt("sscanf")
def sscanf(m, a):
    n = 0
    ptrs = [m.r32(m.uc.reg_read(UC_X86_REG_ESP) + 4 + 4 * (2 + i)) for i in range(16)]
    return u32(scan_c(m, m.cstr(a[0]), m.cstr(a[1]), ptrs))


@crt("fscanf")
def fscanf(m, a):
    f = _file(m, a[0])
    if f is None:
        return 0xFFFFFFFF
    ptrs = [m.r32(m.uc.reg_read(UC_X86_REG_ESP) + 4 + 4 * (2 + i)) for i in range(16)]
    start = f.data.tell()
    rest = f.data.read()
    fmt = m.cstr(a[1])
    # consume one line's worth of input as the source text, then push back what was not used
    text = rest.split(b"\n", 1)[0] if b"\n" not in fmt else rest
    n = scan_c(m, text, fmt, ptrs)
    used = _scan_consumed(text, fmt)
    f.data.seek(start + min(used, len(rest)))
    return u32(n)


def _scan_consumed(text, fmt):
    """Bytes a whole-line scan consumed; the file position moves past the line."""
    i = text.find(b"\n")
    return len(text) if i < 0 else i + 1


# ---- stdio ------------------------------------------------------------------------------------------
class File:
    def __init__(self, path, mode, exists):
        self.path, self.text = path, "b" not in mode
        self.writing = any(c in mode for c in "wa+")
        self.eof = False
        self.rawsize = 0
        if "w" in mode:
            self.host = open(path, "wb")
            self.data = io.BytesIO()
        elif "a" in mode:
            self.host = open(path, "ab")
            self.data = io.BytesIO()
        else:
            raw = open(path, "rb").read()
            self.rawsize = len(raw)
            if self.text:
                raw = raw.replace(b"\r\n", b"\n")
                z = raw.find(b"\x1a")
                if z >= 0:
                    raw = raw[:z]
            self.data = io.BytesIO(raw)
            self.host = open(path, "r+b") if "+" in mode else None


def _file(m, ptr):
    return _state(m)["files"].get(ptr)


IOEOF = 0x10        # FILE._flag at offset 12: MSVC's feof(f) is a macro that tests this bit directly


def _set_eof(m, ptr, on=True):
    flag = m.r32(ptr + 12)
    m.w32(ptr + 12, (flag | IOEOF) if on else (flag & ~IOEOF))


@crt("fopen")
def fopen(m, a):
    path, mode = m.cstr(a[0]).decode("latin-1"), m.cstr(a[1]).decode("latin-1")
    write = any(c in mode for c in "wa+")
    hp, exists = host_path(m.game_root, m.overlay_root, m.cwd, path, for_write=write)
    if write and "r" in mode and not exists:                # r+ on an installed file: copy it up first
        src, ok = host_path(m.game_root, m.overlay_root, m.cwd, path)
        if ok:
            open(hp, "wb").write(open(src, "rb").read())
            exists = True
    if not write and not exists:
        _state(m)["errno"] and m.w32(_state(m)["errno"], 2)
        m.log(f"   fopen({path!r}, {mode!r}) -> not found") if m.state.get("log_files") else None
        return 0
    try:
        f = File(hp, mode, exists)
    except OSError:
        return 0
    ptr = m.alloc(32)
    fd = _state(m)["next_fd"]
    _state(m)["next_fd"] += 1
    m.w32(ptr + 16, fd)                                        # FILE._file
    _state(m)["files"][ptr] = f
    _state(m).setdefault("stdio_fds", {})[fd] = f
    if m.state.get("log_files"):
        m.log(f"   fopen({path!r}, {mode!r}) -> {hp}")
    return ptr


@crt("fclose")
def fclose(m, a):
    f = _state(m)["files"].pop(a[0], None)
    if f is None:
        return 0xFFFFFFFF
    if f.host:
        f.host.close()
    _state(m).get("stdio_fds", {}).pop(m.r32(a[0] + 16), None)
    m.heap.release(a[0])
    return 0


def _write_file(m, ptr, data):
    f = _file(m, ptr)
    if f is None or not f.host:
        return len(data)
    if f.text:
        data = data.replace(b"\n", b"\r\n")
    f.host.write(data)
    return len(data)


@crt("fwrite")
def fwrite(m, a):
    n = a[1] * a[2]
    _write_file(m, a[3], m.rd(a[0], n) if n else b"")
    return a[2]


@crt("fread")
def fread(m, a):
    f = _file(m, a[3])
    if f is None or not a[1]:
        return 0
    data = f.data.read(a[1] * a[2])
    if len(data) < a[1] * a[2]:
        _set_eof(m, a[3])
    if data:
        m.wr(a[0], data)
    return len(data) // a[1]


@crt("fgetc")
def fgetc(m, a):
    f = _file(m, a[0])
    c = f.data.read(1) if f else b""
    if not c and f:
        _set_eof(m, a[0])
    return c[0] if c else 0xFFFFFFFF


@crt("fgets")
def fgets(m, a):
    f = _file(m, a[2])
    if f is None:
        return 0
    limit = max(a[1] - 1, 0)
    line = f.data.readline(limit)
    if not line.endswith(b"\n") and len(line) < limit:        # the read ran into the end of the file
        _set_eof(m, a[2])
    if not line:
        return 0
    m.put_cstr(a[0], line)
    return a[0]


@crt("fseek")
def fseek(m, a):
    f = _file(m, a[0])
    if f is None:
        return 0xFFFFFFFF
    f.data.seek(S32(a[1]), a[2])
    _set_eof(m, a[0], False)
    return 0


@crt("ftell")
def ftell(m, a):
    f = _file(m, a[0])
    return f.data.tell() if f else 0xFFFFFFFF


@crt("_fileno")
def fileno(m, a):
    return m.r32(a[0] + 16) if _file(m, a[0]) else 0xFFFFFFFF


@crt("_filelength")
def filelength(m, a):
    fd = _state(m)["fds"].get(a[0])
    if fd is not None:
        return os.fstat(fd).st_size
    f = _state(m).get("stdio_fds", {}).get(a[0])
    if f is not None:
        return f.rawsize if f.rawsize else os.path.getsize(f.path)
    return 0


# low-level descriptors
@crt("_open")
def _open(m, a):
    path, flags = m.cstr(a[0]).decode("latin-1"), a[1]
    write = flags & 3
    hp, exists = host_path(m.game_root, m.overlay_root, m.cwd, path, for_write=bool(write or flags & 0x100))
    if m.state.get("log_files"):
        m.log(f"   _open({path!r}, flags=0x{flags:x}) -> {hp if exists else 'not found'}")
    if not exists and not flags & 0x100:
        return 0xFFFFFFFF
    of = {0: os.O_RDONLY, 1: os.O_WRONLY, 2: os.O_RDWR}[write]
    if flags & 0x100:
        of |= os.O_CREAT
    if flags & 0x200:
        of |= os.O_TRUNC
    if flags & 8:
        of |= os.O_APPEND
    st = _state(m)
    fd = st["next_fd"]
    st["next_fd"] += 1
    st["fds"][fd] = os.open(hp, of)
    return fd


@crt("_close")
def _close(m, a):
    hostfd = _state(m)["fds"].pop(a[0], None)
    if hostfd is None:
        return 0xFFFFFFFF
    os.close(hostfd)
    return 0


@crt("_read")
def _read(m, a):
    hostfd = _state(m)["fds"].get(a[0])
    if hostfd is None:
        return 0xFFFFFFFF
    data = os.read(hostfd, a[2])
    if data:
        m.wr(a[1], data)
    return len(data)


@crt("_write")
def _write(m, a):
    hostfd = _state(m)["fds"].get(a[0])
    if hostfd is None:
        return a[2]
    return os.write(hostfd, m.rd(a[1], a[2]))


@crt("_lseek")
def _lseek(m, a):
    hostfd = _state(m)["fds"].get(a[0])
    return u32(os.lseek(hostfd, S32(a[1]), a[2])) if hostfd is not None else 0xFFFFFFFF


@crt("_tell")
def _tell(m, a):
    hostfd = _state(m)["fds"].get(a[0])
    return u32(os.lseek(hostfd, 0, 1)) if hostfd is not None else 0xFFFFFFFF


@crt("_chdir")
def chdir(m, a):
    p = normalize(m.cwd, m.cstr(a[0]).decode("latin-1"))
    m.cwd = p
    return 0


@crt("_getcwd")
def getcwd(m, a):
    b = m.cwd.encode()
    if a[0]:
        m.put_cstr(a[0], b)
        return a[0]
    return m.alloc_cstr(b)


@crt("_mkdir")
def mkdir(m, a):
    hp, _ = host_path(m.game_root, m.overlay_root, m.cwd, m.cstr(a[0]).decode("latin-1"), for_write=True)
    os.makedirs(hp, exist_ok=True)
    return 0


# ---- time and random -----------------------------------------------------------------------------------
@crt("time")
def time_(m, a):
    t = int(_time.time())
    if a[0]:
        m.w32(a[0], t)
    return t


@crt("clock")
def clock(m, a):
    return int((_time.time() - _state(m)["t0"]) * 1000)


@crt("ctime")
def ctime(m, a):
    s = _time.strftime("%a %b %d %H:%M:%S %Y\n", _time.localtime(m.r32(a[0])))
    st = _state(m)
    st.setdefault("ctime_buf", m.alloc(32))
    m.put_cstr(st["ctime_buf"], s.encode())
    return st["ctime_buf"]


def _get_seed(m):
    cell = _state(m).get("rand_cell")
    return m.r32(cell) if cell else _state(m)["seed"]


def _set_seed(m, v):
    cell = _state(m).get("rand_cell")           # with the native layer hosted the seed lives in guest memory, where C code shares it
    if cell:
        m.w32(cell, v)
    else:
        _state(m)["seed"] = v


@crt("srand")
def srand(m, a):
    # EMU_SRAND=N: every srand seeds with N, so that a debugging session meets the same world each time (the game seeds from the clock)
    _set_seed(m, int(os.environ["EMU_SRAND"]) if os.environ.get("EMU_SRAND") else a[0])
    return 0


@crt("rand")
def rand(m, a):
    seed = (_get_seed(m) * 214013 + 2531011) & 0xFFFFFFFF          # the MSVC linear congruential generator
    _set_seed(m, seed)
    return (seed >> 16) & 0x7FFF
