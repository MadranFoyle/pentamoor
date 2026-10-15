"""KERNEL32, WINMM, ADVAPI32 and the other small DLLs."""
import os
import struct
import time as _time

from .machine import Block, Cont, ExitProcess, api, u32
from .paths import host_path, normalize

k32 = lambda name, argc: api("kernel32.dll", name, argc)
INVALID_HANDLE = 0xFFFFFFFF


def _st(m):
    st = m.state.setdefault("k32", {})
    if not st:
        st.update(handles={}, next_handle=0x100, timers={}, resources={})
    return st


def new_handle(m, obj):
    st = _st(m)
    h = st["next_handle"]
    st["next_handle"] += 4
    st["handles"][h] = obj
    return h


def now_ms(m):
    """Milliseconds on the virtual clock (instruction-driven, so runs repeat exactly)."""
    return 60000 + int(m.vt * 1000)

# ---- process and module ------------------------------------------------------------------------------
k32("GetVersion", 0)(lambda m, a: 0x88AE0A04)   # Windows 98 SE: 4.10, build 2222, top bit set for Win9x
k32("GetCurrentProcess", 0)(lambda m, a: 0xFFFFFFFF)
k32("GetCurrentThread", 0)(lambda m, a: 0xFFFFFFFE)
k32("GetLastError", 0)(lambda m, a: m.state.get("lasterror", 0))
k32("GetTickCount", 0)(lambda m, a: now_ms(m))
k32("OutputDebugStringA", 1)(lambda m, a: m.log(f"   [debug] {m.cstr(a[0])!r}") or 0)
k32("lstrlenA", 1)(lambda m, a: len(m.cstr(a[0])))

def _cs(m, addr):
    return _st(m).setdefault("cs", {}).setdefault(addr, [None, 0])          # [owner tid, recursion count]


k32("InitializeCriticalSection", 1)(lambda m, a: _st(m).setdefault("cs", {}).__setitem__(a[0], [None, 0]) or 0)
k32("DeleteCriticalSection", 1)(lambda m, a: 0)


@k32("EnterCriticalSection", 1)
def enter_cs(m, a):
    cs = _cs(m, a[0])
    if cs[0] in (None, m.cur.tid):
        cs[0] = m.cur.tid
        cs[1] += 1
        return 0
    return Block(ready=lambda: cs[0] is None)


@k32("LeaveCriticalSection", 1)
def leave_cs(m, a):
    cs = _cs(m, a[0])
    if cs[0] == m.cur.tid:
        cs[1] -= 1
        if cs[1] <= 0:
            cs[0], cs[1] = None, 0
    return 0
k32("GetCurrentThreadId", 0)(lambda m, a: m.cur.tid)
k32("GetThreadPriority", 1)(lambda m, a: 0)
k32("SetThreadPriority", 2)(lambda m, a: 1)
k32("DuplicateHandle", 7)(lambda m, a: (m.w32(a[3], a[1]), 1)[1])


@k32("GetExitCodeThread", 2)
def get_exit_code_thread(m, a):
    obj = _st(m)["handles"].get(a[0])
    done = isinstance(obj, tuple) and obj[0] == "thread" and obj[3].state == "done"
    m.w32(a[1], obj[3].exit_code if done else 259)                      # 259 = STILL_ACTIVE
    return 1

k32("ExitThread", 1)(lambda m, a: m.exit_current_thread(a[0]) or 0)
k32("CloseHandle", 1)(lambda m, a: (_st(m)["handles"].pop(a[0], None), 1)[1])


@k32("WaitForSingleObject", 2)
def wait_for_single_object(m, a):
    obj = _st(m)["handles"].get(a[0])
    if isinstance(obj, tuple) and obj[0] == "thread":
        th = obj[3]
        if th.state == "done":
            return 0
        if a[1] == 0:
            return 0x102                                     # WAIT_TIMEOUT
        return Block(ready=lambda: th.state == "done", until=None if a[1] == 0xFFFFFFFF else m.vt + a[1] / 1000)
    return 0


@k32("DeviceIoControl", 8)
def device_io_control(m, a):
    """MPSTIME.VXD, the game's high-resolution timer: code 1 returns the version, code 2 a tick counter
    (the game divides differences by 0x151d / 100, which gives milliseconds at 54,050 ticks a second)."""
    dev = _st(m)["handles"].get(a[0])
    if dev == ("vxd", "mpstime") and a[4]:
        if a[1] == 1:
            m.w32(a[4], 0x100)
        elif a[1] == 2:
            m.w32(a[4], int(m.vt * 54050))
        if a[6]:
            m.w32(a[6], 4)
        return 1
    return 0


@k32("Sleep", 1)
def sleep(m, a):
    key = ("slept", m.cur.tid)
    st = _st(m)
    if st.get(key):                                            # this is the retry after the wait: done
        st[key] = False
        return 0
    st[key] = True
    return Block(until=m.vt + a[0] / 1000)


@k32("GetModuleHandleA", 1)
def get_module_handle(m, a):
    if not a[0]:
        return m.main["base"]
    name = m.cstr(a[0]).decode("latin-1").lower()
    for n, mod in m.modules.items():
        if n == name or n == name + ".dll" or n.split(".")[0] == name.split(".")[0]:
            return mod["base"]
    return 0


@k32("GetModuleFileNameA", 3)
def get_module_file_name(m, a):
    path = m.exe_guest_path
    for mod in m.modules.values():
        if mod["base"] == a[0] and a[0] != m.main["base"]:
            path = m.cwd + "\\" + os.path.basename(mod["path"]).upper()
    b = path.encode()[:max(a[2] - 1, 0)]
    m.put_cstr(a[1], b)
    return len(b)


@k32("GetCurrentDirectoryA", 2)
def get_cwd(m, a):
    b = m.cwd.encode()
    if a[0] > len(b):
        m.put_cstr(a[1], b)
    return len(b)


@k32("GetStartupInfoA", 1)
def get_startup_info(m, a):
    m.wr(a[0], b"\0" * 68)
    m.w32(a[0], 68)
    m.w32(a[0] + 44, 1)                               # dwFlags: STARTF_USESHOWWINDOW
    m.w16(a[0] + 48, 1)                               # SW_SHOWNORMAL
    return 0


@k32("GetDriveTypeA", 1)
def get_drive_type(m, a):
    m.log(f"   GetDriveTypeA({m.cstr(a[0])!r}) -> 3 (fixed)") if m.state.get("log_files") else None
    return 3


# ---- dynamic loading ----------------------------------------------------------------------------------
@k32("LoadLibraryA", 1)
def load_library(m, a):
    name = m.cstr(a[0]).decode("latin-1")
    if "." not in os.path.basename(name):
        name += ".dll"
    key = os.path.basename(name).lower()
    if key in m.state.get("host_modules", {}):                       # a library the host provides (winemu/magsnd.py)
        m.log(f"   LoadLibraryA({name!r}) -> host module")
        return m.state["host_modules"][key]["base"]
    if key in m.modules:
        return m.modules[key]["base"]
    hp, ok = host_path(m.game_root, m.overlay_root, m.cwd, name if "\\" in name else m.cwd + "\\" + name)
    if not ok:
        m.log(f"   LoadLibraryA({name!r}) -> not found")
        return 0
    mod = m.load_module(hp)
    m.log(f"   LoadLibraryA({name!r}) -> mapped at 0x{mod['base']:08x}, {len(mod['exports'])} exports")
    # DllMain(hinst, DLL_PROCESS_ATTACH, 0)
    return Cont(mod["entry"], [mod["base"], 1, 0], lambda r: mod["base"])


@k32("FreeLibrary", 1)
def free_library(m, a):
    return 1


@k32("GetProcAddress", 2)
def get_proc_address(m, a):
    name = m.cstr(a[1]).decode("latin-1") if a[1] > 0xFFFF else f"#{a[1]}"
    for mod in m.state.get("host_modules", {}).values():
        if mod["base"] == a[0]:
            return mod["exports"].get(name, 0)
    for mod in m.modules.values():
        if mod["base"] == a[0]:
            addr = mod["exports"].get(name)
            if addr:
                return addr
    return 0


# ---- memory --------------------------------------------------------------------------------------------
@k32("GlobalAlloc", 2)
def global_alloc(m, a):
    return m.alloc(a[1], zero=bool(a[0] & 0x40))


k32("GlobalLock", 1)(lambda m, a: a[0])
k32("GlobalUnlock", 1)(lambda m, a: 1)
k32("GlobalHandle", 1)(lambda m, a: a[0])
k32("GlobalFree", 1)(lambda m, a: m.heap.release(a[0]) or 0)


# ---- files ---------------------------------------------------------------------------------------------
class FileHandle:
    def __init__(self, path, fd):
        self.path, self.fd = path, fd


@k32("CreateFileA", 7)
def create_file(m, a):
    path, access, disp = m.cstr(a[0]).decode("latin-1"), a[1], a[4]
    write = bool(access & 0x40000000)
    if path.startswith("\\\\.\\"):                              # a Windows 9x virtual device (VxD)
        dev = path[4:].lower()
        if dev.startswith("mpstime"):
            h = new_handle(m, ("vxd", "mpstime"))
            if m.clock_cells:
                m.w32(m.clock_cells[2], h)   # hosted C code answers the timer driver's calls for this handle itself
            return h
        m.log(f"   CreateFileA({path!r}): unknown device")
        return INVALID_HANDLE
    if path.startswith("\\\\"):
        return INVALID_HANDLE
    hp, exists = host_path(m.game_root, m.overlay_root, m.cwd, path, for_write=write or disp in (1, 2, 4))
    if m.state.get("log_files"):
        m.log(f"   CreateFileA({path!r}, access=0x{access:x}, disp={disp}) -> {hp if exists else 'not found'}")
    if not exists and disp in (3, 5):                 # OPEN_EXISTING / TRUNCATE_EXISTING
        m.state["lasterror"] = 2
        return INVALID_HANDLE
    if exists and os.path.isdir(hp) and not a[5] & 0x02000000:     # a directory needs FILE_FLAG_BACKUP_SEMANTICS
        m.state["lasterror"] = 5
        return INVALID_HANDLE
    flags = os.O_RDWR if write else os.O_RDONLY
    if disp in (1, 2, 4):
        flags |= os.O_CREAT
    if disp in (2, 5):
        flags |= os.O_TRUNC
    return new_handle(m, FileHandle(hp, os.open(hp, flags)))


@k32("ReadFile", 5)
def read_file(m, a):
    h = _st(m)["handles"].get(a[0])
    if not isinstance(h, FileHandle):
        return 0
    try:
        data = os.read(h.fd, a[2])
    except OSError:
        m.state["lasterror"] = 5
        return 0
    if data:
        m.wr(a[1], data)
    if a[3]:
        m.w32(a[3], len(data))
    return 1


@k32("GetFileSize", 2)
def get_file_size(m, a):
    h = _st(m)["handles"].get(a[0])
    return os.fstat(h.fd).st_size if isinstance(h, FileHandle) else INVALID_HANDLE


@k32("CopyFileA", 3)
def copy_file(m, a):
    src, ok = host_path(m.game_root, m.overlay_root, m.cwd, m.cstr(a[0]).decode("latin-1"))
    dst, _ = host_path(m.game_root, m.overlay_root, m.cwd, m.cstr(a[1]).decode("latin-1"), for_write=True)
    if not ok:
        return 0
    open(dst, "wb").write(open(src, "rb").read())
    return 1


@k32("CreateFileMappingA", 6)
def create_mapping(m, a):
    """Named or anonymous (hFile == -1) shared memory, or a view of a file."""
    st = _st(m)
    name = m.cstr(a[5]).decode("latin-1") if a[5] else None
    if a[0] == INVALID_HANDLE:
        size = a[4]
        blocks = st.setdefault("named_maps", {})
        if name and name in blocks:
            base = blocks[name]
        else:
            base = m.alloc(size)
            if name:
                blocks[name] = base
        return new_handle(m, ("mapping", None, base, size))
    h = st["handles"].get(a[0])
    return new_handle(m, ("mapping", h, 0, 0)) if isinstance(h, FileHandle) else 0


@k32("MapViewOfFile", 5)
def map_view(m, a):
    kind = _st(m)["handles"].get(a[0])
    if not (isinstance(kind, tuple) and kind[0] == "mapping"):
        return 0
    _, h, base, size = kind
    if h is None:                                        # anonymous block: the view is the block itself
        return base + a[3]
    fsize = os.fstat(h.fd).st_size
    p = m.alloc(fsize, zero=False)
    os.lseek(h.fd, 0, 0)
    m.wr(p, os.read(h.fd, fsize))
    return p + a[3]


k32("UnmapViewOfFile", 1)(lambda m, a: 1)


@k32("CreateThread", 6)
def create_thread(m, a):
    t = m.spawn(a[2], [a[3]], f"thread@0x{a[2]:08x}", stack=max(a[1], 0x40000) * 8)
    m.log(f"   CreateThread(start=0x{a[2]:08x}, arg=0x{a[3]:08x}) -> thread {t.tid}")
    if a[5]:
        m.w32(a[5], t.tid)
    return new_handle(m, ("thread", a[2], a[3], t))


# ---- profile (ini) -------------------------------------------------------------------------------------
def _ini(m, file):
    hp, ok = host_path(m.game_root, m.overlay_root, m.cwd, file)
    sections = {}
    if ok:
        cur = None
        for line in open(hp, errors="replace"):
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                cur = sections.setdefault(line[1:-1].lower(), {})
            elif "=" in line and cur is not None:
                k, v = line.split("=", 1)
                cur[k.strip().lower()] = v.strip()
    return sections


@k32("GetPrivateProfileIntA", 4)
def profile_int(m, a):
    v = _ini(m, m.cstr(a[3]).decode("latin-1")).get(m.cstr(a[0]).decode().lower(), {}).get(m.cstr(a[1]).decode().lower())
    try:
        return u32(int(v))
    except (TypeError, ValueError):
        return a[2]


@k32("GetPrivateProfileStringA", 6)
def profile_string(m, a):
    sec, key = m.cstr(a[0]).decode("latin-1").lower(), m.cstr(a[1]).decode("latin-1").lower()
    v = _ini(m, m.cstr(a[5]).decode("latin-1")).get(sec, {}).get(key)
    b = v.encode("latin-1") if v is not None else m.cstr(a[2])
    b = b[:max(a[4] - 1, 0)]
    m.put_cstr(a[3], b)
    return len(b)


# ---- resources -----------------------------------------------------------------------------------------
def find_resource(m, hmod, name, rtype):
    import pefile
    mod = next((x for x in m.modules.values() if x["base"] == (hmod or m.main["base"])), m.main)
    pe = mod["pe"]
    if not hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
        return None
    def key(v):
        return v if v < 0x10000 else m.cstr(v).decode("latin-1").upper()
    want_t, want_n = key(rtype), key(name)
    for t in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        tid = t.id if t.id is not None else (t.name.decode() if isinstance(t.name, bytes) else str(t.name)).upper()
        if tid != want_t:
            continue
        for n in t.directory.entries:
            nid = n.id if n.id is not None else (n.name.decode() if isinstance(n.name, bytes) else str(n.name)).upper()
            if nid != want_n:
                continue
            leaf = n.directory.entries[0].data.struct
            return mod["base"] + leaf.OffsetToData, leaf.Size
    return None


@k32("FindResourceA", 3)
def find_resource_a(m, a):
    r = find_resource(m, a[0], a[1], a[2])
    return new_handle(m, ("resource", r)) if r else 0


@k32("LoadResource", 2)
def load_resource(m, a):
    return a[1]


@k32("LockResource", 1)
def lock_resource(m, a):
    obj = _st(m)["handles"].get(a[0])
    return obj[1][0] if obj else 0


# ---- WINMM ---------------------------------------------------------------------------------------------
@api("winmm.dll", "timeBeginPeriod", 1)
def time_begin_period(m, a):
    return 0


api("winmm.dll", "timeEndPeriod", 1)(lambda m, a: 0)


@api("winmm.dll", "timeSetEvent", 5)
def time_set_event(m, a):
    delay, res, cb, user, flags = a
    st = _st(m)
    tid = len(st["timers"]) + 1
    st["timers"][tid] = {"delay": max(delay, 1), "cb": cb, "user": user, "periodic": bool(flags & 1),
                         "next": now_ms(m) + max(delay, 1)}
    m.log(f"   timeSetEvent(delay={delay}, cb=0x{cb:08x}, {'periodic' if flags & 1 else 'one-shot'}) -> {tid}")
    return tid


@api("winmm.dll", "timeKillEvent", 1)
def time_kill_event(m, a):
    _st(m)["timers"].pop(a[0], None)
    return 0


def on_schedule(m):
    """Multimedia timers run their callback on a short-lived thread, like the real timer thread does."""
    st, t = _st(m), now_ms(m)
    for tid, tm in list(st["timers"].items()):
        if tm["next"] <= t:
            running = tm.get("thread")
            if running is not None and running.state != "done":
                continue                                            # previous tick still running: skip this one
            tm["thread"] = m.spawn(tm["cb"], [tid, 0, tm["user"], 0, 0], f"timer{tid}", one_shot=True,
                                   stack=0x10000)
            if tm["periodic"]:
                tm["next"] = t + tm["delay"]
            else:
                st["timers"].pop(tid)


# ---- ADVAPI32 (registry) -------------------------------------------------------------------------------
@api("advapi32.dll", "RegOpenKeyExA", 5)
def reg_open(m, a):
    return 2                                            # ERROR_FILE_NOT_FOUND: the game falls back to defaults


@api("advapi32.dll", "RegCreateKeyExA", 9)
def reg_create(m, a):
    if a[7]:
        m.w32(a[7], new_handle(m, ("regkey", m.cstr(a[1]))))
    if a[8]:
        m.w32(a[8], 1)
    return 0


api("advapi32.dll", "RegQueryValueExA", 6)(lambda m, a: 2)
api("advapi32.dll", "RegSetValueExA", 6)(lambda m, a: 0)
api("advapi32.dll", "RegFlushKey", 1)(lambda m, a: 0)
api("advapi32.dll", "RegCloseKey", 1)(lambda m, a: 0)

# ---- the rest ------------------------------------------------------------------------------------------
api("shell32.dll", "SHAppBarMessage", 2)(lambda m, a: 0)
api("comctl32.dll", "#17", 0)(lambda m, a: 0)              # InitCommonControls
api("comdlg32.dll", "GetSaveFileNameA", 1)(lambda m, a: 0)
