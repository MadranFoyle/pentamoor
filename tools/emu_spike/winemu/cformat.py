"""printf / scanf formatting for the emulated C runtime."""
import re
import struct

SPEC = re.compile(rb"%([-+ #0]*)(\*|\d+)?(?:\.(\*|\d+))?(hh|h|ll|l|L|I64)?([diouxXcsfeEgGpn%])")


class VaReader:
    """Pulls varargs from emulated stack memory starting at `addr` (a cdecl call or a va_list)."""
    def __init__(self, m, addr):
        self.m, self.addr = m, addr

    def int(self):
        v = self.m.r32(self.addr)
        self.addr += 4
        return v

    def double(self):
        v = struct.unpack("<d", self.m.rd(self.addr, 8))[0]
        self.addr += 8
        return v


def format_c(m, fmt, va):
    out, pos = b"", 0
    for mo in SPEC.finditer(fmt):
        out += fmt[pos:mo.start()]
        pos = mo.end()
        flags, width, prec, size, conv = mo.groups()
        conv = conv.decode()
        if conv == "%":
            out += b"%"
            continue
        if width == b"*":
            width = str(struct.unpack("<i", struct.pack("<I", va.int()))[0]).encode()
        if prec == b"*":
            prec = str(va.int()).encode()
        py = "%" + flags.decode() + (width.decode() if width else "") + ("." + prec.decode() if prec is not None else "")
        if conv in "di":
            v = va.int()
            if size == b"h":
                v &= 0xFFFF
                v = v - 0x10000 if v & 0x8000 else v
            else:
                v = v - 0x100000000 if v & 0x80000000 else v
            out += ((py + "d") % v).encode()
        elif conv in "ouxX":
            v = va.int() & (0xFFFF if size == b"h" else 0xFFFFFFFF)
            out += ((py + conv) % v).encode()
        elif conv == "c":
            out += ((py + "s") % chr(va.int() & 0xFF)).encode("latin-1")
        elif conv == "s":
            p = va.int()
            s = m.cstr(p) if p else b"(null)"
            if prec is not None:
                s = s[:int(prec)]
            out += ((py.split(".")[0] + "s") % s.decode("latin-1")).encode("latin-1")
        elif conv in "feEgG":
            out += ((py + conv) % va.double()).encode()
        elif conv == "p":
            out += b"%08X" % va.int()
        elif conv == "n":
            va.int()
    return out + fmt[pos:]


def _num_re(kind):
    return {"d": r"[+-]?\d+", "u": r"\d+", "x": r"(?:0[xX])?[0-9a-fA-F]+", "f": r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"}[kind]


def scan_c(m, text, fmt, ptrs):
    """Minimal sscanf: %d %i %u %x %o %s %c %f %lf %[set] and literal matching. Returns items assigned."""
    i, n, items = 0, 0, 0
    j = 0
    while j < len(fmt):
        c = fmt[j:j + 1]
        if c == b"%":
            j += 1
            skip = False
            if fmt[j:j + 1] == b"*":
                skip = True
                j += 1
            w = b""
            while fmt[j:j + 1].isdigit():
                w += fmt[j:j + 1]
                j += 1
            size = b""
            while fmt[j:j + 1] in (b"l", b"h", b"L"):
                size += fmt[j:j + 1]
                j += 1
            conv = fmt[j:j + 1]
            j += 1
            width = int(w) if w else None
            if conv == b"%":
                if text[i:i + 1] != b"%":
                    break
                i += 1
                continue
            if conv not in (b"c", b"["):
                while i < len(text) and text[i:i + 1].isspace():
                    i += 1
            if i >= len(text) and conv != b"n":
                return items if items else 0xFFFFFFFF
            if conv in (b"d", b"i", b"u", b"x", b"X", b"o", b"f", b"e", b"g"):
                kind = {b"d": "d", b"i": "d", b"u": "u", b"x": "x", b"X": "x", b"o": "u"}.get(conv, "f")
                mo = re.compile(_num_re(kind).encode()).match(text, i, i + width if width else len(text))
                if not mo:
                    break
                i = mo.end()
                if skip:
                    continue
                p = ptrs[n]
                n += 1
                if kind == "f":
                    v = float(mo.group())
                    m.wr(p, struct.pack("<d" if b"l" in size else "<f", v))
                else:
                    v = int(mo.group(), 16 if kind == "x" else (8 if conv == b"o" else 10)) & 0xFFFFFFFF
                    m.wr(p, struct.pack("<H", v & 0xFFFF) if b"h" in size else struct.pack("<I", v))
                items += 1
            elif conv == b"s":
                k = i
                while k < len(text) and not text[k:k + 1].isspace() and (width is None or k - i < width):
                    k += 1
                if not skip:
                    m.put_cstr(ptrs[n], text[i:k])
                    n += 1
                    items += 1
                i = k
            elif conv == b"c":
                cnt = width or 1
                if not skip:
                    m.wr(ptrs[n], text[i:i + cnt])
                    n += 1
                    items += 1
                i += cnt
            elif conv == b"[":
                k = j
                if fmt[k:k + 1] == b"^":
                    k += 1
                if fmt[k:k + 1] == b"]":
                    k += 1
                while fmt[k:k + 1] != b"]":
                    k += 1
                spec = fmt[j:k]
                j = k + 1
                neg = spec.startswith(b"^")
                chars = spec[1:] if neg else spec
                allowed = set()
                x = 0
                while x < len(chars):
                    if x + 2 < len(chars) and chars[x + 1:x + 2] == b"-":
                        allowed.update(range(chars[x], chars[x + 2] + 1))
                        x += 3
                    else:
                        allowed.add(chars[x])
                        x += 1
                k = i
                while k < len(text) and ((text[k] in allowed) != neg) and (width is None or k - i < width):
                    k += 1
                if k == i:
                    break
                if not skip:
                    m.put_cstr(ptrs[n], text[i:k])
                    n += 1
                    items += 1
                i = k
        elif c.isspace():
            while i < len(text) and text[i:i + 1].isspace():
                i += 1
            j += 1
        else:
            if text[i:i + 1] != c:
                break
            i += 1
            j += 1
    return items
