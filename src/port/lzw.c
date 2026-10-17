/*
 * lzw.c - the game's picture decompressor, written out by hand from its machine code (the MPS_CODE section, 0x70d000-0x70d4a8).
 *
 * The lifter cannot take it: it keeps decoded strings on a private stack that it switches to with `xchg esp`, returns through `jmp ebp`
 * after popping its own return address, and passes arguments in registers. Its state lives at fixed addresses, kept here (the game's
 * other code reads some of it): the input pointer [0x706500] and its end [0x5327b0], a refill callback [0x67f43c], the dictionary
 * (3 bytes an entry: a 16-bit prefix, a suffix byte) at 0x532860, the code width [0x536876] with its limit [0x536877] and mask
 * [0x536878], the bit buffer [0x536880] and its fill [0x536884], the next code [0x53687c], the previous code [0x536886], the first
 * character of the last string [0x53688a], and the run-length state [0x536874] (repeats pending) and [0x536875] (the byte).
 * It is LZW with variable code width plus a run-length escape (0x90, a count; a count of 0 is a literal 0x90).
 */
#include <string.h>

#include "port.h"
#include "profile.h"

/* The same code is in MAGIC.EXE (0x70d000), DUEL.EXE (0x6c5000) and DECKDLL.DLL (its MPS_CODE section), with its state at other addresses: the block holding the dictionary and the
 * flags is the same length and moved as a whole; the input pointer and its end, the refill callback and the function it calls are placed apart. Where each copy is, is in the
 * build's profile (profile.c: `lzw`, ProfLzw); what is inside the block is the same in every copy (profile.h, LZW_*: offsets from the dictionary). The addresses in the
 * comments below are MAGIC.EXE 1.0's. */
static __thread const ProfLzw *lz;
#define Z(off) (lz->block + (off))

typedef struct State {
    uint32_t eax, ebx, ecx, edx, esi, edi;
    uint32_t sp;            /* the private data stack: grows down from the block's LZW_STACK_BASE (0x536c8b in MAGIC.EXE) */
} State;

/* esi = the input pointer, refilled from the callback when it has reached the end; ebx, ecx and edx survive the call, as the original saves them. */
static void input_ready(State *s)
{
    if (s->esi >= RD32(lz->in_end)) {
        guest_call(RD32(lz->refill), 0, NULL);
        s->esi = RD32(lz->in_ptr);
    }
}

static uint32_t fetch_word(State *s)
{
    uint32_t w;

    input_ready(s);
    w = RD16(s->esi);
    s->esi += 2;
    return w;
}

/* 0x70d2b5: start the dictionary again (also reached by falling out of the initialiser). */
static void reset_codes(State *s)
{
    uint32_t i;

    WR8(Z(LZW_WIDTH), 9);
    WR32(Z(LZW_MASK), 0x1ff);
    s->edx = 0x100;
    WR32(Z(LZW_NEXT), s->edx);
    for (i = 0; i < 0x800; i++)
        WR16(Z(LZW_DICT) + 3 * i, 0xFFFF);
    for (i = 0; i < 0x100; i++)
        WR8(Z(LZW_DICT) + 3 * i + 2, (uint8_t)i);
    s->eax = 0xFFFFFF00u;
    s->ebx = 0x300;
    s->ecx = 0;
}

/* 0x70d245: begin a picture: nothing if its size is zero; else clear the run state, point the data stack at its base, read the maximum code width. */
static void init_picture(State *s)
{
    uint32_t w;

    s->eax = RD32(Z(LZW_SIZE_LO)) | RD32(Z(LZW_SIZE_HI));
    if (!s->eax)
        return;
    WR8(Z(LZW_REPEAT), 0);
    WR8(Z(LZW_BYTE), 0);
    WR32(Z(LZW_STACK_PTR), Z(LZW_STACK_BASE));
    w = fetch_word(s);
    WR32(lz->in_ptr, s->esi);               /* (the original keeps its pointer in esi here and stores it at the caller's end) */
    if ((w & 0xFF) > 0xb)
        w = (w & ~0xFFu) | 0xb;
    WR8(Z(LZW_WIDTH_MAX), (uint8_t)w);
    WR32(Z(LZW_BITS), w & 0xFFFF);
    WR8(Z(LZW_BITFILL), 8);
    reset_codes(s);
}

/* 0x70d392: the next decoded byte. Strings come off the private stack; when it is empty the next code is read and its string pushed
 * (the last suffix pushed is the string's first character, which is the one returned). */
static uint32_t next_byte(State *s)
{
    uint32_t ebx, ecx, eax;
    int8_t cl, ch;

    if (s->sp != Z(LZW_STACK_BASE)) {
        s->eax = RD32(s->sp);
        s->sp += 4;
        return s->eax & 0xFF;
    }
    ebx = RD32(Z(LZW_BITS));
    ch = (int8_t)RD8(Z(LZW_BITFILL));
    cl = (int8_t)(0x10 - ch);
    ebx >>= (uint8_t)cl & 31;
    cl = ch;
    while (cl < (int8_t)RD8(Z(LZW_WIDTH))) {                 /* the bit buffer is refilled a word at a time */
        input_ready(s);
        eax = RD16(s->esi);
        s->esi += 2;
        WR32(Z(LZW_BITS), eax);
        eax <<= (uint8_t)cl & 31;
        ebx |= eax;
        cl = (int8_t)(cl + 0x10);
    }
    cl = (int8_t)(cl - (int8_t)RD8(Z(LZW_WIDTH)));
    WR8(Z(LZW_BITFILL), (uint8_t)cl);
    eax = ebx & RD32(Z(LZW_MASK));
    ecx = eax;
    if ((int32_t)eax >= (int32_t)s->edx) {              /* the code is the one being defined: its string is the previous one and that one's first character */
        ecx = s->edx;
        eax = RD32(Z(LZW_PREV));
        ebx = (ebx & ~0xFFu) | RD8(Z(LZW_FIRST));
        s->sp -= 4;
        WR32(s->sp, ebx);
    }
    for (;;) {                                           /* walk the prefixes, pushing each suffix */
        uint32_t prefix;

        ebx = eax * 3;
        prefix = RD16(Z(LZW_DICT) + ebx);
        eax = (eax & ~0xFFFFu) | prefix;
        if (prefix == 0xFFFF)
            break;
        ebx = (ebx & ~0xFFu) | RD8(Z(LZW_DICT) + ebx + 2);
        s->sp -= 4;
        WR32(s->sp, ebx);
    }
    /* the root: ebx is still its entry's offset */
    eax = (eax & ~0xFFu) | RD8(Z(LZW_DICT) + ebx + 2);
    WR8(Z(LZW_FIRST), (uint8_t)eax);
    s->sp -= 4;
    WR32(s->sp, eax);
    ebx = s->edx * 3;                                    /* define the new code: the previous string plus this first character */
    WR8(Z(LZW_DICT) + ebx + 2, (uint8_t)eax);
    eax = RD32(Z(LZW_PREV));
    WR16(Z(LZW_DICT) + ebx, (uint16_t)eax);
    s->edx++;
    if ((int32_t)s->edx > (int32_t)RD32(Z(LZW_MASK))) {     /* the code width grows */
        WR8(Z(LZW_WIDTH), (uint8_t)(RD8(Z(LZW_WIDTH)) + 1));
        WR32(Z(LZW_MASK), (RD32(Z(LZW_MASK)) << 1) | 1);
    }
    if ((int8_t)RD8(Z(LZW_WIDTH)) > (int8_t)RD8(Z(LZW_WIDTH_MAX))) { /* past the maximum width: start the dictionary again (which leaves ecx 0) */
        reset_codes(s);
        ecx = s->ecx;
    }
    WR32(Z(LZW_PREV), ecx);
    s->ecx = ecx;
    s->eax = RD32(s->sp);
    s->sp += 4;
    return s->eax & 0xFF;
}

/* 0x70d300: decode `count` bytes (a count of pairs of nibbles in nibble mode, each decoded byte giving two output bytes) to edi. */
static uint32_t decode(State *s, uint32_t count)
{
    uint32_t eax = 0;

    if (RD8(Z(LZW_NIBBLE)))
        count = (count + 1) >> 1;
    WR32(Z(LZW_COUNT), count);
    s->edx = RD32(Z(LZW_NEXT));
    s->sp = RD32(Z(LZW_STACK_PTR));
    for (;;) {
        uint32_t al;
        uint32_t left;

        if (RD8(Z(LZW_REPEAT)) == 0) {
            al = next_byte(s);
            if (al != 0x90) {
                WR8(Z(LZW_BYTE), (uint8_t)al);
            } else {
                al = next_byte(s);
                if (al == 0) {
                    al = 0x90;
                    WR8(Z(LZW_BYTE), 0x90);
                } else {
                    WR8(Z(LZW_REPEAT), (uint8_t)(al - 1));
                    al = RD8(Z(LZW_BYTE));
                    WR8(Z(LZW_REPEAT), (uint8_t)(RD8(Z(LZW_REPEAT)) - 1));
                }
            }
        } else {
            al = RD8(Z(LZW_BYTE));
            WR8(Z(LZW_REPEAT), (uint8_t)(RD8(Z(LZW_REPEAT)) - 1));
        }
        if (RD8(Z(LZW_NIBBLE))) {                              /* nibble mode: the low nibble, then the high one */
            uint32_t ah = (al >> 4) & 0xF;

            al &= 0xF;
            WR8(s->edi, (uint8_t)al);
            WR8(s->edi + 1, (uint8_t)ah);
            s->edi += 2;
            eax = al | ah << 8;
        } else {
            WR8(s->edi, (uint8_t)al);
            s->edi++;
            eax = (eax & ~0xFFu) | al;
        }
        left = RD32(Z(LZW_COUNT)) - 1;
        WR32(Z(LZW_COUNT), left);
        if (!left)
            break;
    }
    WR32(Z(LZW_NEXT), s->edx);
    WR32(Z(LZW_STACK_PTR), s->sp);
    return eax;
}

/* 0x70d484 and 0x70d1fc: decode `count` bytes to `dst`, continuing from the saved input pointer. */
static uint32_t read_impl(const uint32_t *a)
{
    State s;
    uint32_t eax;

    memset(&s, 0, sizeof(s));
    s.esi = RD32(lz->in_ptr);
    s.edi = a[0];
    eax = decode(&s, a[1]);
    WR32(lz->in_ptr, s.esi);
    return eax;
}

/* 0x70d000(arg): read the picture file's records from the input stream: 'M0'/'M1' records (a marker word, a length word, then that many bytes) are
 * copied into the table at Z(LZW_DICT) (or to arg, or after the first word), until the 'X' record, which gives the picture's parameters and starts the
 * decoder. */
static uint32_t header_impl(const uint32_t *a)
{
    State s;

    memset(&s, 0, sizeof(s));
    for (;;) {
        uint32_t w, edi, start, len, k;

        s.esi = RD32(lz->in_ptr);
        w = fetch_word(&s);
        WR32(lz->in_ptr, s.esi);
        if ((w & 0xFF) == 0x58) {
            WR8(Z(LZW_NIBBLE), (uint8_t)((w >> 8) & 1));
            s.esi = RD32(lz->in_ptr);
            w = fetch_word(&s);
            WR32(lz->in_ptr, s.esi);
            WR32(Z(LZW_PARAM), w);
            w = fetch_word(&s);
            WR32(lz->in_ptr, s.esi);
            WR32(Z(LZW_SIZE_LO), w);
            w = fetch_word(&s);
            WR32(lz->in_ptr, s.esi);
            WR32(Z(LZW_SIZE_HI), w);
            init_picture(&s);
            return s.eax;
        }
        edi = Z(LZW_DICT);
        if (w == 0x304d || w == 0x314d) {
            if ((int32_t)a[0] < 1)
                edi += 2;
            else if (a[0] != 1)
                edi = a[0];
        }
        start = edi;
        WR16(edi, (uint16_t)w);
        edi += 2;
        s.esi = RD32(lz->in_ptr);
        w = fetch_word(&s);
        WR32(lz->in_ptr, s.esi);
        WR16(edi, (uint16_t)w);
        edi += 2;
        len = w >> 1;
        for (k = 0; k < len; k++) {
            s.esi = RD32(lz->in_ptr);
            w = fetch_word(&s);
            WR32(lz->in_ptr, s.esi);
            WR16(edi, (uint16_t)w);
            edi += 2;
        }
        if (start == Z(LZW_DICT)) {
            uint32_t arg = Z(LZW_DICT);

            guest_call(lz->callback, 1, &arg);
        }
    }
}


/* One set of entry points per copy of the code (an override carries no context, so each copy gets functions that select its own). A process has the program's own copy and, in
 * each of up to LIB_COPIES libraries, another (1.0: DECKDLL.DLL; 2.15: deckdll.dll and drawcardlib.dll); the profile of each says where its entries and its state are (profile.c). */
#define LIB_COPIES 3
static const ProfLzw *prog_copy, *lib_copy[LIB_COPIES];
static int nlib_copies;

#define ENTRY(name, ctx, impl) static uint32_t name(const uint32_t *a) { const ProfLzw *saved = lz; uint32_t r; lz = ctx; r = impl(a); lz = saved; return r; }
ENTRY(prog_header, prog_copy, header_impl)
ENTRY(prog_read, prog_copy, read_impl)
ENTRY(lib0_header, lib_copy[0], header_impl)
ENTRY(lib0_read, lib_copy[0], read_impl)
ENTRY(lib1_header, lib_copy[1], header_impl)
ENTRY(lib1_read, lib_copy[1], read_impl)
ENTRY(lib2_header, lib_copy[2], header_impl)
ENTRY(lib2_read, lib_copy[2], read_impl)

static const struct { HostGuestFn header, read; } LIB_ENTRY[LIB_COPIES] = {{lib0_header, lib0_read}, {lib1_header, lib1_read}, {lib2_header, lib2_read}};

static void install_copy(const ProfLzw *c, HostGuestFn header, HostGuestFn read)
{
    port_override(c->header, header, 3, 0);
    port_override(c->read, read, 2, 0);
    port_override(c->read2, read, 2, 0);
}

/* The program's own copy (MAGIC.EXE's MPS_CODE at 0x70d000, DUEL.EXE's at 0x6c5000), if the build's profile has one. */
void lzw_reset(void) { nlib_copies = 0; }              /* port_hooks_reset: the overrides are gone, so are the copies they stood for */

void lzw_install(void)
{
    nlib_copies = 0;
    if (!profile->lzw.header)
        return;
    prog_copy = &profile->lzw;
    install_copy(prog_copy, prog_header, prog_read);
}

/* The copy in a library, when the library is mapped (modules.c): DECKDLL.DLL's MPS_CODE section, at the base the library was lifted for. */
void lzw_install_library(const BuildProfile *lib, uint32_t base)
{
    if (!lib->lzw.header || lib->base != base)
        return;
    if (nlib_copies == LIB_COPIES)
        port_fatal("more libraries with a picture decompressor than the runtime has room for (%d)", LIB_COPIES);
    lib_copy[nlib_copies] = &lib->lzw;
    install_copy(lib_copy[nlib_copies], LIB_ENTRY[nlib_copies].header, LIB_ENTRY[nlib_copies].read);
    nlib_copies++;
}
