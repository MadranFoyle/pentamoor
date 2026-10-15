"""The KERNEL32 calls a statically-linked C runtime makes at start-up and for its heap, plus locale and time."""
import struct
import time as _time

from .kernel32 import FileHandle, INVALID_HANDLE, _st, new_handle
from .machine import ExitProcess, api
from .paths import host_path, normalize
from .crt import _ctype_table

k32 = lambda name, argc: api("kernel32.dll", name, argc)


# ---- heap and virtual memory -------------------------------------------------------------------------------
k32("HeapCreate", 3)(lambda m, a: new_handle(m, ("heap",)))
k32("HeapDestroy", 1)(lambda m, a: 1)
k32("HeapValidate", 3)(lambda m, a: 1)
k32("HeapFree", 3)(lambda m, a: m.heap.release(a[2]) or 1)


@k32("HeapAlloc", 3)
def heap_alloc(m, a):
    return m.alloc(a[2], zero=bool(a[1] & 8))


@k32("HeapReAlloc", 4)
def heap_realloc(m, a):
    q = m.alloc(a[3], zero=bool(a[1] & 8))
    if a[2]:
        n = min(m.heap.size(a[2]), a[3])
        if n:
            m.wr(q, m.rd(a[2], n))
        m.heap.release(a[2])
    return q


@k32("VirtualAlloc", 4)
def virtual_alloc(m, a):
    p = m.alloc(a[1] + 4096)
    return (p + 4095) & ~4095


k32("VirtualFree", 3)(lambda m, a: 1)
k32("IsBadReadPtr", 2)(lambda m, a: 0)
k32("IsBadWritePtr", 2)(lambda m, a: 0)
k32("InterlockedIncrement", 1)(lambda m, a: (m.w32(a[0], m.r32(a[0]) + 1), m.r32(a[0]))[1])
k32("InterlockedDecrement", 1)(lambda m, a: (m.w32(a[0], m.r32(a[0]) - 1), m.r32(a[0]))[1])


# ---- process -------------------------------------------------------------------------------------------------
@k32("ExitProcess", 1)
def exit_process(m, a):
    raise ExitProcess(a[0])


@k32("TerminateProcess", 2)
def terminate_process(m, a):
    raise ExitProcess(a[1])


k32("UnhandledExceptionFilter", 1)(lambda m, a: 0)
k32("RtlUnwind", 4)(lambda m, a: 0)
k32("DebugBreak", 0)(lambda m, a: 0)
k32("SetConsoleCtrlHandler", 2)(lambda m, a: 1)
k32("SetHandleCount", 1)(lambda m, a: a[0])
k32("SetEnvironmentVariableA", 2)(lambda m, a: 1)
k32("GetStdHandle", 1)(lambda m, a: 0x10 + (0xFFFFFFFF - a[0] if a[0] > 0xFFFFFFF0 else 0))
k32("SetStdHandle", 2)(lambda m, a: 1)
k32("GetFileType", 1)(lambda m, a: 1 if isinstance(_st(m)["handles"].get(a[0]), FileHandle) else 2)


@k32("GetCommandLineA", 0)
def get_command_line(m, a):
    st = _st(m)
    if "cmdline" not in st:
        st["cmdline"] = m.alloc_cstr(m.state.get("command_line", m.exe_guest_path).encode())
    return st["cmdline"]


@k32("GetEnvironmentStrings", 0)
def get_env_strings(m, a):
    st = _st(m)
    if "env" not in st:
        st["env"] = m.alloc(16)
    return st["env"]


k32("GetEnvironmentStringsW", 0)(lambda m, a: get_env_strings(m, a))
k32("FreeEnvironmentStringsA", 1)(lambda m, a: 1)
k32("FreeEnvironmentStringsW", 1)(lambda m, a: 1)


@k32("SetCurrentDirectoryA", 1)
def set_cwd(m, a):
    m.cwd = normalize(m.cwd, m.cstr(a[0]).decode("latin-1"))
    return 1


@k32("CreateDirectoryA", 2)
def create_directory(m, a):
    import os
    hp, _ = host_path(m.game_root, m.overlay_root, m.cwd, m.cstr(a[0]).decode("latin-1"), for_write=True)
    os.makedirs(hp, exist_ok=True)
    return 1


# ---- files ----------------------------------------------------------------------------------------------------
@k32("WriteFile", 5)
def write_file(m, a):
    import os
    h = _st(m)["handles"].get(a[0])
    n = a[2]
    if isinstance(h, FileHandle):
        n = os.write(h.fd, m.rd(a[1], a[2]))
    if a[3]:
        m.w32(a[3], n)
    return 1


@k32("SetFilePointer", 4)
def set_file_pointer(m, a):
    import os
    h = _st(m)["handles"].get(a[0])
    if not isinstance(h, FileHandle):
        return INVALID_HANDLE
    lo = a[1] - 0x100000000 if a[1] & 0x80000000 else a[1]
    return os.lseek(h.fd, lo, a[3]) & 0xFFFFFFFF


k32("SetEndOfFile", 1)(lambda m, a: 1)
k32("FlushFileBuffers", 1)(lambda m, a: 1)


# ---- locale and strings ----------------------------------------------------------------------------------------
k32("GetACP", 0)(lambda m, a: 1252)
k32("GetOEMCP", 0)(lambda m, a: 437)


@k32("GetCPInfo", 2)
def get_cp_info(m, a):
    m.wr(a[1], struct.pack("<I2B", 1, 0x3F, 0) + b"\0" * 12)
    return 1


@k32("CompareStringA", 6)
def compare_string(m, a):
    x = m.cstr(a[2]) if a[3] == 0xFFFFFFFF else m.rd(a[2], a[3])
    y = m.cstr(a[4]) if a[5] == 0xFFFFFFFF else m.rd(a[4], a[5])
    if a[1] & 1:
        x, y = x.lower(), y.lower()
    return 1 if x < y else 3 if x > y else 2


@k32("CompareStringW", 6)
def compare_string_w(m, a):
    x = (m.cstr(a[2], 4096) if False else m.rd(a[2], 2 * a[3])) if a[3] != 0xFFFFFFFF else b""
    y = m.rd(a[4], 2 * a[5]) if a[5] != 0xFFFFFFFF else b""
    return 1 if x < y else 3 if x > y else 2


def _lcmap(m, a, wide):
    unit = 2 if wide else 1
    n = a[3] if a[3] != 0xFFFFFFFF else len(m.cstr(a[2])) + 1
    data = m.rd(a[2], n * unit)
    if not wide:
        if a[1] & 0x100:
            data = data.lower()
        elif a[1] & 0x200:
            data = data.upper()
    if a[5]:
        m.wr(a[4], data[:a[5] * unit])
    return n


k32("LCMapStringA", 6)(lambda m, a: _lcmap(m, a, False))
k32("LCMapStringW", 6)(lambda m, a: _lcmap(m, a, True))


@k32("MultiByteToWideChar", 6)
def mb_to_wide(m, a):
    n = a[3] if a[3] != 0xFFFFFFFF else len(m.cstr(a[2])) + 1
    src = m.rd(a[2], n)
    if a[5]:
        m.wr(a[4], b"".join(struct.pack("<H", c) for c in src[:a[5]]))
    return n


@k32("WideCharToMultiByte", 8)
def wide_to_mb(m, a):
    if a[3] == 0xFFFFFFFF:
        n, s = 0, b""
        while True:
            c = m.r16(a[2] + 2 * n)
            n += 1
            s += bytes([c & 0xFF])
            if c == 0:
                break
    else:
        n = a[3]
        s = bytes(m.r16(a[2] + 2 * i) & 0xFF for i in range(n))
    if a[5]:
        m.wr(a[4], s[:a[5]])
    return n


@k32("GetStringTypeW", 4)
def get_string_type_w(m, a):
    t = _ctype_table(m)["ctype"]
    n = a[2] if a[2] != 0xFFFFFFFF else 0
    for i in range(n):
        c = m.r16(a[1] + 2 * i)
        f = struct.unpack("<H", m.rd(t + 2 * c, 2))[0] if c < 256 else 0
        m.w16(a[3] + 2 * i, f)
    return 1


@k32("GetStringTypeA", 5)
def get_string_type_a(m, a):
    t = _ctype_table(m)["ctype"]
    n = a[3] if a[3] != 0xFFFFFFFF else len(m.cstr(a[2]))
    for i in range(n):
        c = m.rd(a[2] + i, 1)[0]
        m.w16(a[4] + 2 * i, struct.unpack("<H", m.rd(t + 2 * c, 2))[0])
    return 1


# ---- time -------------------------------------------------------------------------------------------------------
def _systemtime(m, p, t):
    m.wr(p, struct.pack("<8H", t.tm_year, t.tm_mon, (t.tm_wday + 1) % 7, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, 0))


k32("GetLocalTime", 1)(lambda m, a: _systemtime(m, a[0], _time.localtime()) or 0)
k32("GetSystemTime", 1)(lambda m, a: _systemtime(m, a[0], _time.gmtime()) or 0)
k32("GetTimeZoneInformation", 1)(lambda m, a: (m.wr(a[0], b"\0" * 172), 0)[1])
api("comdlg32.dll", "GetOpenFileNameA", 1)(lambda m, a: 0)
