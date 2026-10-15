/* mkpe.c - writes the smallest PE32 program the runtime can load: stub.exe, for `make check-program`. Not a program of the game's and holding no code of it: one byte of "code"
 * (a ret, never run: the stub game module's lifted function at the entry point runs instead), and an import table for kernel32.dll's ExitProcess, CreateFileA, WriteFile and
 * CloseHandle, whose address-table slots are where stubgame/handlers_gen.c calls them (0x402100, +4, +8, +12).
 *   mkpe stub.exe */
#include <stdio.h>
#include <string.h>

static unsigned char img[0x600];

static void put16(unsigned at, unsigned v) { img[at] = (unsigned char)v; img[at + 1] = (unsigned char)(v >> 8); }
static void put32(unsigned at, unsigned v) { put16(at, v & 0xFFFF); put16(at + 2, v >> 16); }

int main(int argc, char **argv)
{
    static const char *const names[4] = {"ExitProcess", "CreateFileA", "WriteFile", "CloseHandle"};
    unsigned i, opt = 0x58, sec = 0x138, idata = 0x400;     /* file offsets; the .idata section is at RVA 0x2000 */
    FILE *f;

    if (argc != 2) {
        fprintf(stderr, "usage: mkpe out.exe\n");
        return 2;
    }
    memcpy(img, "MZ", 2);
    put32(0x3c, 0x40);                                      /* e_lfanew */
    memcpy(img + 0x40, "PE\0\0", 4);
    put16(0x44, 0x14c);                                     /* i386 */
    put16(0x46, 2);                                         /* two sections */
    put16(0x54, 0xE0);                                      /* the optional header's size */
    put16(0x56, 0x0102);                                    /* executable, 32-bit */
    put16(opt, 0x10b);                                      /* PE32 */
    put32(opt + 4, 0x200);                                  /* size of code */
    put32(opt + 8, 0x200);                                  /* of initialised data */
    put32(opt + 16, 0x1000);                                /* the entry point's RVA */
    put32(opt + 20, 0x1000);                                /* base of code */
    put32(opt + 24, 0x2000);                                /* base of data */
    put32(opt + 28, 0x400000);                              /* the image base */
    put32(opt + 32, 0x1000);                                /* section alignment */
    put32(opt + 36, 0x200);                                 /* file alignment */
    put16(opt + 40, 4);                                     /* OS version 4.0 */
    put16(opt + 48, 4);                                     /* subsystem version 4.0 */
    put32(opt + 56, 0x3000);                                /* size of image */
    put32(opt + 60, 0x200);                                 /* size of headers */
    put16(opt + 68, 2);                                     /* the Windows GUI subsystem */
    put32(opt + 72, 0x100000);
    put32(opt + 76, 0x1000);
    put32(opt + 80, 0x100000);
    put32(opt + 84, 0x1000);
    put32(opt + 92, 16);                                    /* data directories */
    put32(opt + 104, 0x2000);                               /* directory 1: imports */
    put32(opt + 108, 0x28);
    memcpy(img + sec, ".text", 5);
    put32(sec + 8, 0x10);
    put32(sec + 12, 0x1000);
    put32(sec + 16, 0x200);
    put32(sec + 20, 0x200);
    put32(sec + 36, 0x60000020);
    memcpy(img + sec + 40, ".idata", 6);
    put32(sec + 40 + 8, 0x200);
    put32(sec + 40 + 12, 0x2000);
    put32(sec + 40 + 16, 0x200);
    put32(sec + 40 + 20, 0x400);
    put32(sec + 40 + 36, 0xC0000040);
    img[0x200] = 0xC3;                                      /* ret */

    put32(idata + 0x00, 0x2080);                            /* the descriptor: names (the lookup table) */
    put32(idata + 0x0c, 0x2060);                            /* the library's name */
    put32(idata + 0x10, 0x2100);                            /* the address table the loader fills */
    memcpy(img + idata + 0x60, "KERNEL32.dll", 13);
    for (i = 0; i < 4; i++) {
        unsigned entry = 0xA0 + 0x10 * i;                   /* a hint (2 bytes) and the name */

        memcpy(img + idata + entry + 2, names[i], strlen(names[i]) + 1);
        put32(idata + 0x80 + 4 * i, 0x2000 + entry);
        put32(idata + 0x100 + 4 * i, 0x2000 + entry);
    }
    f = fopen(argv[1], "wb");
    if (!f || fwrite(img, 1, sizeof(img), f) != sizeof(img) || fclose(f) != 0) {
        fprintf(stderr, "mkpe: cannot write %s\n", argv[1]);
        return 1;
    }
    return 0;
}
