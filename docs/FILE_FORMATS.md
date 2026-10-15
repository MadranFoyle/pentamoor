# Game file formats

What is known about the graphics files in the 1997 retail install, **checked against the real
files** (344 `.SPR` files with 13,107 sprites, 313 `.PIC` files) rather than copied from the
decompiled code. Anything not checked is listed as unknown. The retail files live in
`sources/installed/Magic/Program` (see [ORACLE_VM.md](ORACLE_VM.md) for how they were obtained).

## `.SPR` sprite archives

Verified layout of a file:

```
record 0 | record 1 | ... | record N-1 | int32 -1 | 12 more bytes
```

- The records are walked with the first field, `int32 total_size`, which is the distance to the
  next record. Walking this way reaches the `-1` terminator in **all 344 files**, and exactly 12
  bytes follow it in every file (contents not decoded).
- `total_size` is a multiple of 4 in all 13,107 records. Each record's data is padded to 4 bytes.
- A record starts with a 16-byte header: `int32 total_size`, then six `int16` fields. The decompiled
  sprite code names them `width, height, clip_left, clip_top, offset_y, visible_height`. Only
  `visible_height` was checked: it is the number of encoded rows in the record.
- Each encoded row is: one byte of leading skip (`0xFF` means the whole row is empty), then one
  length byte, and if that byte is `0xFE` the real length is in the next byte, then that many pixel
  bytes (palette indices). Decoding `visible_height` rows this way lands within the record's padding
  for **13,102 of 13,107 records**. Five records do not fit (2,918, 34, 11, 10 and 2 spare bytes);
  they are unexplained.
- Not verified: what the six header fields mean, what distinguishes the `0xFE` form from a plain
  length (the old doc claimed an "opaque block" fast path), and whether palette index 0 is
  transparent inside a run.

Where they are: 35 in the program folder, and the same 103 sprite sets three times in `SPR`,
`SPR800` and `SPR1024`, one set per screen resolution.

The decoder of the old SDL2 port (removed; it was in `src/magic/sidlib/sprite.c`) loaded
`ICONS.SPR` and reported 24 sprites, matching the 24 records found by the independent walk above.

## `.PIC` image files

**These are not PCX files.** An earlier version of this document said they were "authentic ZSoft
PCX version 5"; none of the 313 files starts with the PCX byte `0x0A`. They start with two ASCII
bytes:

| Magic | Files | Where |
|---|---|---|
| `X0` | 257 | 40 in the program folder, 33 in `CardArt`, 42 in `DBArt`, 85 in `DuelArt`, 57 in `FACES` |
| `M1` | 35 | program folder (for example `ADVINTER.pic`, `ADVFAC64.PIC`, `BUYCARDS.PIC`) |
| `M0` | 21 | program folder (for example `ART.PIC`, `CSTLINE.PIC`) |

Nothing else is verified here. The loaders were `Pic_DecodeKimpicHeader` and
`Pic_DecodeKimpicScanline`, and the upstream decompilation's README said the card art uses a Haar wavelet codec;
that has not been confirmed. The
image dimensions, the palette and the compression are all undocumented so far.

## How to re-check

The scripts used for the numbers above were throwaway one-offs. To repeat the `.SPR` check, walk
each file by `total_size` until `-1`, then decode `visible_height` rows per record as described
and compare the consumed length with `total_size`.
