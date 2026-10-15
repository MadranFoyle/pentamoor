"""
blast.py - PKWARE Data Compression Library "explode" (the format the game's InstallShield 3 archive stores its files in), in plain Python.

A stream starts with two bytes: 0 for literals of eight raw bits or 1 for Huffman-coded ones, and the dictionary size (4, 5 or 6: 1, 2 or 4 KiB).
Everything after is bits, least significant first; Huffman codes are read bit by bit and inverted. The code tables are the format's own.
"""

_LITLEN = bytes([11, 124, 8, 7, 28, 7, 188, 13, 76, 4, 10, 8, 12, 10, 12, 10, 8, 23, 8, 9, 7, 6, 7, 8, 7, 6, 55, 8, 23, 24, 12, 11, 7, 9, 11, 12, 6, 7, 22, 5, 7, 24, 6, 11,
                 9, 6, 7, 22, 7, 11, 38, 7, 9, 8, 25, 11, 8, 11, 9, 12, 8, 12, 5, 38, 5, 38, 5, 11, 7, 5, 6, 21, 6, 10, 53, 8, 7, 24, 10, 27, 44, 253, 253, 253, 252, 252,
                 252, 13, 12, 45, 12, 45, 12, 61, 12, 45, 44, 173])
_LENLEN = bytes([2, 35, 36, 53, 38, 23])
_DISTLEN = bytes([2, 20, 53, 230, 247, 151, 248])
_BASE = (3, 2, 4, 5, 6, 7, 8, 9, 10, 12, 16, 24, 40, 72, 136, 264)
_EXTRA = (0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8)


def _construct(rep):
    """(count of codes per length, symbols in code order) for a table given as (length | (repeat - 1) << 4) bytes."""
    lengths = []
    for b in rep:
        lengths.extend([b & 15] * ((b >> 4) + 1))
    count = [0] * 16
    for n in lengths:
        count[n] += 1
    offs = [0] * 16
    for n in range(1, 15):
        offs[n + 1] = offs[n] + count[n]
    symbol = [0] * len(lengths)
    for sym, n in enumerate(lengths):
        if n:
            symbol[offs[n]] = sym
            offs[n] += 1
    return count, symbol


_LIT, _LEN, _DIST = _construct(_LITLEN), _construct(_LENLEN), _construct(_DISTLEN)


class BlastError(Exception):
    pass


def blast(data, expect=None):
    """The bytes a stream of imploded data holds. `expect` is the length the caller knows: output stops there."""
    if len(data) < 2 or data[0] > 1 or not 4 <= data[1] <= 6:
        raise BlastError("not a PKWARE DCL stream")
    lit, dict_bits = data[0], data[1]
    pos, bitbuf, bitcnt = 2, 0, 0
    out = bytearray()
    n = len(data)

    def bits(need):
        nonlocal pos, bitbuf, bitcnt
        while bitcnt < need:
            if pos >= n:
                raise BlastError("stream ends early")
            bitbuf |= data[pos] << bitcnt
            pos += 1
            bitcnt += 8
        v = bitbuf & ((1 << need) - 1)
        bitbuf >>= need
        bitcnt -= need
        return v

    def decode(table):
        count, symbol = table
        code = first = index = 0
        for length in range(1, 16):
            code |= bits(1) ^ 1
            c = count[length]
            if code - c < first:
                return symbol[index + (code - first)]
            index += c
            first += c
            first <<= 1
            code <<= 1
        raise BlastError("bad code")

    while True:
        if bits(1):                                            # a length and a distance
            sym = decode(_LEN)
            length = _BASE[sym] + bits(_EXTRA[sym])
            if length == 519:                                  # the end
                break
            shift = 2 if length == 2 else dict_bits
            dist = (decode(_DIST) << shift) + bits(shift) + 1
            if dist > len(out):
                raise BlastError("distance too far back")
            start = len(out) - dist
            if dist >= length:
                out += out[start:start + length]
            else:                                              # overlapping: repeats
                for i in range(length):
                    out.append(out[start + i])
        else:
            out.append(decode(_LIT) if lit else bits(8))
        if expect is not None and len(out) >= expect:
            break
    return bytes(out)
