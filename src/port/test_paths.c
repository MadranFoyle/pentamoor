/* test_paths.c - the guest's file names on the host (paths.c): case, backslashes, drive letters, the overlay that takes what the game writes, copying a
 * file up from the installed folder, and the two folders' listings together. The checks on names that differ only in case need a file system that tells
 * them apart (Linux's; macOS's usually does not), and say so when they skip.
 *   make -C src/port test */
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "filedlg.h"
#include "plat.h"
#include "port.h"
#include "test_util.h"
#include "wm.h"

int pe_find_resource(uint32_t hinst, uint32_t type, uint32_t name, uint32_t *addr, uint32_t *size) { (void)hinst; (void)type; (void)name; (void)addr; (void)size; return 0; }

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static char root[600], over[600];

static void put(const char *rel, const char *text)       /* a file (and the folders above it) under the installed folder */
{
    char path[1300], *q;
    FILE *f;

    snprintf(path, sizeof(path), "%s/%s", root, rel);
    for (q = path + strlen(root) + 1; *q; q++)
        if (*q == '/') {
            *q = 0;
            plat_mkdir(path);
            *q = '/';
        }
    f = fopen(path, "wb");
    if (f) {
        fputs(text, f);
        fclose(f);
    }
}

static void put_over(const char *rel, const char *text)  /* the same, in the overlay */
{
    char path[1300], *q;
    FILE *f;

    snprintf(path, sizeof(path), "%s/%s", over, rel);
    for (q = path + strlen(over) + 1; *q; q++)
        if (*q == '/') {
            *q = 0;
            plat_mkdir(path);
            *q = '/';
        }
    f = fopen(path, "wb");
    if (f) {
        fputs(text, f);
        fclose(f);
    }
}

static int exists(const char *dir, const char *rel)
{
    char path[1300];

    snprintf(path, sizeof(path), "%s/%s", dir, rel);
    return access(path, F_OK) == 0;
}

static int contents_are(const char *path, const char *text)
{
    char buf[256] = "";
    FILE *f = fopen(path, "rb");

    if (!f)
        return 0;
    buf[fread(buf, 1, sizeof(buf) - 1, f)] = 0;
    fclose(f);
    return !strcmp(buf, text);
}

static int has_name(const char *dir, const char *name)    /* is there an entry spelled exactly so (the file system may match without regard to case, a listing does not) */
{
    DIR *d = opendir(dir);
    struct dirent *e;
    int found = 0;

    while (d && (e = readdir(d)))
        if (!strcmp(e->d_name, name))
            found = 1;
    if (d)
        closedir(d);
    return found;
}

static int case_sensitive(void)
{
    char a[700], b[700];
    int sensitive;

    snprintf(a, sizeof(a), "%s/casetest", root);
    snprintf(b, sizeof(b), "%s/CASETEST", root);
    plat_mkdir(a);
    sensitive = access(b, F_OK) != 0;
    rmdir(a);
    return sensitive;
}

typedef struct { char names[16][64]; int n; } Names;

static void collect(const char *name, int is_dir, void *ctx)
{
    Names *n = ctx;

    if (n->n < 16 && !is_dir)
        snprintf(n->names[n->n++], 64, "%s", name);
}

static int listed(const Names *n, const char *name)
{
    int i;

    for (i = 0; i < n->n; i++)
        if (!strcmp(n->names[i], name))
            return 1;
    return 0;
}

int main(void)
{
    char tmpl[300], out[1300], norm[400];
    int sensitive, i;
    Names names;

    test_tmpdir(tmpl, sizeof(tmpl), "pentamoor_paths_");
    CHECK(tmpl[0] != 0);
    snprintf(root, sizeof(root), "%s/game", tmpl);
    snprintf(over, sizeof(over), "%s/overlay", tmpl);
    plat_mkdir(root);
    plat_mkdir(over);
    put("Program/Sound/LOCMUS1.WAV", "music");
    put("Program/DuelArt/Damage.pic", "pic");
    put("Program/CARDS.DAT", "cards");
    put("Program/Decks/0001.DCK", "d1");
    put("Program/Decks/0002.DCK", "d2");
    put("Program/saveDescs", "0) (Used By Duel)\r\n");
    paths_init(root, over);
    sensitive = case_sensitive();
    printf("file system tells names apart by case: %s\n", sensitive ? "yes" : "no (those checks are skipped)");

    /* the game's names: relative to the working directory, either slash, any case, a drive letter that means nothing */
    snprintf(guest_cwd, sizeof(guest_cwd), "C:\\Magic\\Program");
    CHECK(paths_host("sound\\locmus1.wav", 0, out, sizeof(out)) == 1);
    snprintf(norm, sizeof(norm), "%s/Program/Sound/LOCMUS1.WAV", root);
    CHECK(!strcmp(out, norm));
    CHECK(paths_host("C:\\MAGIC\\PROGRAM\\DuelArt\\Damage.pic", 0, out, sizeof(out)) == 1);
    snprintf(norm, sizeof(norm), "%s/Program/DuelArt/Damage.pic", root);
    CHECK(!strcmp(out, norm));
    CHECK(paths_host("\\MAGIC\\PROGRAM\\duelart\\DAMAGE.PIC", 0, out, sizeof(out)) == 1);
    CHECK(paths_host("C:sound\\LocMus1.Wav", 0, out, sizeof(out)) == 1);        /* the drive's own current folder (C:sound\x) */
    CHECK(paths_host("D:CARDS.DAT", 0, out, sizeof(out)) == 1);                 /* a drive letter is no folder (D:file) */
    CHECK(paths_host("c:/magic/program/cards.dat", 0, out, sizeof(out)) == 1);
    CHECK(paths_host("..\\Program\\.\\CARDS.DAT", 0, out, sizeof(out)) == 1);
    CHECK(paths_host("nothing.bin", 0, out, sizeof(out)) == 0);
    CHECK(!exists(over, "Program"));                                            /* a read makes nothing */
    CHECK(paths_host("sound\\nothing.wav", 0, out, sizeof(out)) == 0);

    /* writing: the overlay, with the installed folder's spelling for a name it has, the game's for one it does not */
    CHECK(paths_host("C:\\MAGIC\\PROGRAM\\MAGIC4.SVE", 1, out, sizeof(out)) == 0);
    snprintf(norm, sizeof(norm), "%s/Program/MAGIC4.SVE", over);
    CHECK(!strcmp(out, norm));
    CHECK(has_name(over, "Program") && !has_name(over, "PROGRAM"));
    CHECK(paths_host("savegame\\AUTOSAVE.SVG", 1, out, sizeof(out)) == 0);
    snprintf(norm, sizeof(norm), "%s/Program/savegame/AUTOSAVE.SVG", over);
    CHECK(!strcmp(out, norm));
    CHECK(has_name(over, "Program") && exists(over, "Program/savegame"));
    {
        FILE *f = fopen(out, "wb");

        CHECK(f != NULL);
        if (f) {
            fputs("auto", f);
            fclose(f);
        }
    }
    CHECK(paths_host("SaveGame\\autosave.svg", 0, out, sizeof(out)) == 1);       /* back, whatever the case */
    CHECK(contents_are(out, "auto"));
    CHECK(paths_host("SAVEGAME\\autosave.svg", 1, out, sizeof(out)) == 1);       /* again for writing: the same file, not a second spelling */
    snprintf(norm, sizeof(norm), "%s/Program/savegame/AUTOSAVE.SVG", over);
    CHECK(!strcmp(out, norm));
    CHECK(!exists(root, "Program/savegame"));                                    /* the installed folder is never touched */
    CHECK(!exists(root, "Program/MAGIC4.SVE"));

    /* a write from scratch does not carry the installed file's contents; one into the file does */
    CHECK(paths_host("saveDescs", 1, out, sizeof(out)) == 0);
    CHECK(!exists(over, "Program/saveDescs"));
    CHECK(paths_host("savedescs", 2, out, sizeof(out)) == 1);                    /* copied up, under the installed spelling */
    snprintf(norm, sizeof(norm), "%s/Program/saveDescs", over);
    CHECK(!strcmp(out, norm));
    CHECK(contents_are(out, "0) (Used By Duel)\r\n"));
    put_over("Program/saveDescs", "changed");
    CHECK(paths_host("saveDescs", 2, out, sizeof(out)) == 1 && contents_are(out, "changed"));   /* the overlay's own is not copied over */
    CHECK(paths_host("saveDescs", 0, out, sizeof(out)) == 1 && contents_are(out, "changed"));   /* read: the overlay shadows the installed */
    CHECK(paths_host("cards.dat", 2, out, sizeof(out)) == 1 && contents_are(out, "cards"));
    CHECK(paths_host("nothing.dat", 2, out, sizeof(out)) == 0);                  /* nothing to copy up: a new file */

    /* the two folders listed together; the overlay's file shadows the installed one of the same name in another case */
    put_over("Program/Decks/0002.dck", "mine");
    put_over("Program/Decks/MINE.DCK", "new");
    memset(&names, 0, sizeof(names));
    paths_list("Decks", collect, &names);
    CHECK(names.n == 3);
    CHECK(listed(&names, "0001.DCK") && listed(&names, "MINE.DCK"));
    CHECK(listed(&names, "0002.dck") || (!sensitive && listed(&names, "0002.DCK")));
    CHECK(!(listed(&names, "0002.dck") && listed(&names, "0002.DCK")));
    memset(&names, 0, sizeof(names));
    paths_list("C:\\MAGIC\\PROGRAM\\DECKS", collect, &names);
    CHECK(names.n == 3);
    memset(&names, 0, sizeof(names));
    paths_list("Nowhere", collect, &names);
    CHECK(names.n == 0);
    memset(&names, 0, sizeof(names));
    paths_list("Sound", collect, &names);                                        /* only the installed folder has it */
    CHECK(names.n == 1 && listed(&names, "LOCMUS1.WAV"));

    if (sensitive) {
        /* an overlay with both PROGRAM and Program (older runs on Linux made that): a file in either is found, the exact spelling is preferred, and
         * a name made later goes where the existing folder is */
        put_over("PROGRAM/Only.Upper", "u");
        put_over("PROGRAM/Both.TXT", "upper");
        put_over("Program/Both.TXT", "mixed");
        CHECK(paths_host("C:\\MAGIC\\PROGRAM\\only.upper", 0, out, sizeof(out)) == 1 && contents_are(out, "u"));
        CHECK(paths_host("C:\\MAGIC\\Program\\both.txt", 0, out, sizeof(out)) == 1 && contents_are(out, "mixed"));
        CHECK(paths_host("C:\\MAGIC\\PROGRAM\\BOTH.TXT", 0, out, sizeof(out)) == 1 && contents_are(out, "upper"));
        CHECK(paths_host("..\\Program\\Both.TXT", 0, out, sizeof(out)) == 1 && contents_are(out, "mixed"));
        /* names in the installed folder that differ only by case: the exact one wins */
        put("Program/Dup/readme.txt", "lower");
        put("Program/Dup/README.TXT", "upper");
        CHECK(paths_host("Dup\\README.TXT", 0, out, sizeof(out)) == 1 && contents_are(out, "upper"));
        CHECK(paths_host("Dup\\readme.txt", 0, out, sizeof(out)) == 1 && contents_are(out, "lower"));
        /* a folder spelled differently in the installed tree and asked for another way */
        put("Program/Mixed Case/File.One", "1");
        CHECK(paths_host("mixed case\\file.one", 0, out, sizeof(out)) == 1 && contents_are(out, "1"));
        CHECK(paths_host("MIXED CASE\\new.file", 1, out, sizeof(out)) == 0);
        CHECK(has_name(over, "Program") && exists(over, "Program/Mixed Case"));
        {
            char dir[700];

            snprintf(dir, sizeof(dir), "%s/Program", over);
            CHECK(has_name(dir, "Mixed Case") && !has_name(dir, "MIXED CASE"));
        }
        memset(&names, 0, sizeof(names));
        paths_list("C:\\Magic\\PROGRAM", collect, &names);                       /* both overlay spellings and the installed one, each name once */
        CHECK(listed(&names, "Only.Upper") && listed(&names, "CARDS.DAT"));
    }


    /* the file dialogs' path and filter logic (filedlg.c) */
    {
        FdFilter f[4];
        char buf[600], name[300];
        int fo, fe;
        static const char filt[] = "Deck files (*.dck)\0*.dck\0Text and lists\0*.txt; *.lst\0All Files (*.*)\0*.*\0\0";
        static const char lone[] = "Orphan\0";

        CHECK(fd_parse_filter(filt, sizeof(filt), f, 4) == 3);
        CHECK(!strcmp(f[0].desc, "Deck files (*.dck)") && !strcmp(f[0].pat, "*.dck"));
        CHECK(!strcmp(f[1].pat, "*.txt; *.lst") && !strcmp(f[2].pat, "*.*"));
        CHECK(fd_parse_filter(filt, sizeof(filt), f, 2) == 2);                       /* no more than asked for */
        CHECK(fd_parse_filter(lone, sizeof(lone), f, 4) == 0);                       /* a description with no pattern is dropped */
        CHECK(fd_parse_filter("", 1, f, 4) == 0);

        CHECK(fd_wild_match("*.dck", "0001.DCK") && fd_wild_match("*.DCK", "x.dck") && !fd_wild_match("*.dck", "x.dckx"));
        CHECK(fd_wild_match("*.*", "README") && fd_wild_match("*", "README") && fd_wild_match("a?c", "ABC") && !fd_wild_match("a?c", "ac"));
        CHECK(fd_wild_match("magic*.sve", "MAGIC3.SVE") && fd_wild_match("*d*k*", "deck") && !fd_wild_match("*.dck", ""));
        CHECK(fd_filter_match("*.txt; *.lst", "a.LST") && fd_filter_match("*.txt;*.lst", "b.txt") && !fd_filter_match("*.txt;*.lst", "c.dck"));
        CHECK(!fd_filter_match("", "a.txt") && fd_has_wild("a*") && fd_has_wild("?") && !fd_has_wild("deck.dck"));

        fd_name_of("C:\\Magic\\Program\\a.dck", name, sizeof(name));
        CHECK(!strcmp(name, "a.dck"));
        fd_name_of("a/b.txt", name, sizeof(name));
        CHECK(!strcmp(name, "b.txt"));
        fd_name_of("plain", name, sizeof(name));
        CHECK(!strcmp(name, "plain"));
        fd_dir_of("C:\\Magic\\a.dck", buf, sizeof(buf));
        CHECK(!strcmp(buf, "C:\\Magic"));
        fd_dir_of("C:\\a.dck", buf, sizeof(buf));
        CHECK(!strcmp(buf, "C:\\"));
        CHECK(fd_parent("C:\\Magic\\Program", buf, sizeof(buf)) == 1 && !strcmp(buf, "C:\\Magic"));
        CHECK(fd_parent("C:\\Magic", buf, sizeof(buf)) == 1 && !strcmp(buf, "C:\\"));
        CHECK(fd_parent("C:\\", buf, sizeof(buf)) == 0 && !strcmp(buf, "C:\\"));
        snprintf(buf, sizeof(buf), "C:\\Magic\\Program");
        CHECK(fd_parent(buf, buf, sizeof(buf)) == 1 && !strcmp(buf, "C:\\Magic"));    /* in place */
        fd_join("C:\\Magic", "x.dck", buf, sizeof(buf));
        CHECK(!strcmp(buf, "C:\\Magic\\x.dck"));
        fd_join("C:\\", "x.dck", buf, sizeof(buf));
        CHECK(!strcmp(buf, "C:\\x.dck"));

        fd_resolve("C:\\Magic\\Program", "a.dck", buf, sizeof(buf));
        CHECK(!strcmp(buf, "C:\\Magic\\Program\\a.dck"));
        fd_resolve("C:\\Magic\\Program", "..\\b.dck", buf, sizeof(buf));
        CHECK(!strcmp(buf, "C:\\Magic\\b.dck"));
        fd_resolve("C:\\Magic\\Program", "d:/Other/c.dck", buf, sizeof(buf));
        CHECK(!strcmp(buf, "D:\\Other\\c.dck"));
        fd_resolve("C:\\Magic\\Program", "\\Magic\\Decks", buf, sizeof(buf));
        CHECK(!strcmp(buf, "C:\\Magic\\Decks"));
        fd_resolve("C:\\Magic\\Program", "  \"My Deck.dck\"  ", buf, sizeof(buf));
        CHECK(!strcmp(buf, "C:\\Magic\\Program\\My Deck.dck"));
        fd_resolve("C:\\Magic\\Program", "Decks\\", buf, sizeof(buf));
        CHECK(!strcmp(buf, "C:\\Magic\\Program\\Decks"));
        fd_resolve("C:\\Magic\\Program", "C:\\", buf, sizeof(buf));
        CHECK(!strcmp(buf, "C:\\"));
        fd_resolve("C:\\Magic\\Program", "..\\..\\..\\..\\x", buf, sizeof(buf));        /* above the root stays at the root */
        CHECK(!strcmp(buf, "C:\\x"));
        fd_resolve("C:\\Magic\\Program", "", buf, sizeof(buf));
        CHECK(!strcmp(buf, "C:\\Magic\\Program"));
        fd_resolve("C:\\Magic\\Program", ".", buf, sizeof(buf));
        CHECK(!strcmp(buf, "C:\\Magic\\Program"));

        CHECK(fd_has_ext("C:\\a.b\\deck") == 0 && fd_has_ext("C:\\a\\deck.dck") == 1 && fd_has_ext("deck.") == 1);
        snprintf(buf, sizeof(buf), "C:\\Magic\\deck");
        fd_add_defext(buf, sizeof(buf), "dck");
        CHECK(!strcmp(buf, "C:\\Magic\\deck.dck"));
        fd_add_defext(buf, sizeof(buf), "txt");                                          /* already has one */
        CHECK(!strcmp(buf, "C:\\Magic\\deck.dck"));
        snprintf(buf, sizeof(buf), "C:\\dir.d\\deck");
        fd_add_defext(buf, sizeof(buf), ".sve");                                         /* a dot in a folder does not count; a leading dot is dropped */
        CHECK(!strcmp(buf, "C:\\dir.d\\deck.sve"));
        snprintf(buf, sizeof(buf), "C:\\x");
        fd_add_defext(buf, sizeof(buf), "");
        fd_add_defext(buf, sizeof(buf), NULL);
        CHECK(!strcmp(buf, "C:\\x"));
        snprintf(buf, sizeof(buf), "C:\\x");
        fd_add_defext(buf, sizeof(buf), "*.SVG");                                        /* as DUEL.EXE hands it over */
        CHECK(!strcmp(buf, "C:\\x.SVG"));
        snprintf(buf, sizeof(buf), "C:\\x");
        fd_add_defext(buf, sizeof(buf), "a*b");                                          /* a pattern is no extension */
        CHECK(!strcmp(buf, "C:\\x"));
        snprintf(buf, sizeof(buf), "C:\\x");
        fd_add_defext(buf, 5, "dck");                                                    /* does not fit: unchanged */
        CHECK(!strcmp(buf, "C:\\x"));

        fd_offsets("C:\\dir1\\dir2\\file.ext", &fo, &fe);
        CHECK(fo == 13 && fe == 18);                                                     /* the documented example's shape */
        fd_offsets("C:\\a.b\\file", &fo, &fe);
        CHECK(fo == 7 && fe == 0);                                                       /* no extension */
        fd_offsets("C:\\x.", &fo, &fe);
        CHECK(fo == 3 && fe == 5);                                                       /* a trailing period: at the terminator */
        fd_offsets("name.dck", &fo, &fe);
        CHECK(fo == 0 && fe == 5);
    }

    /* the host layer (plat.h): the pattern matcher the file dialogs' directory lists use, mkdir -p, the same-file test, the guest's address space */
    {
        char deep[1400], f1[1400], f2[1400];
        uint8_t chunk[5000], got[5000];
        int fd, k;
        FILE *f;

        CHECK(port_glob("*.WAV", "LOCMUS1.WAV") && !port_glob("*.WAV", "LOCMUS1.WAVX") && port_glob("*", "") && port_glob("*.*", "A.B") && !port_glob("*.*", "AB"));
        CHECK(port_glob("MAGIC?.SVE", "MAGIC4.SVE") && !port_glob("MAGIC?.SVE", "MAGIC.SVE") && port_glob("[AB]*", "BX") && !port_glob("[AB]*", "CX"));
        CHECK(port_glob("[A-C]?", "B1") && port_glob("[!A-C]?", "D1") && !port_glob("[!A-C]?", "B1") && port_glob("a*b*c", "aXbYbzc") && !port_glob("a*b*c", "aXbY"));
        CHECK(port_glob("[", "[") && port_glob("\\*", "*") && !port_glob("\\*", "x"));

        snprintf(deep, sizeof(deep), "%s/mk/a b/c", tmpl);
        paths_mkdirs(deep);
        CHECK(exists(tmpl, "mk/a b/c"));
        paths_mkdirs(deep);                                                      /* again: nothing to do */
        snprintf(f1, sizeof(f1), "%s/mk/one.txt", tmpl);
        snprintf(f2, sizeof(f2), "%s/mk/two.txt", tmpl);
        f = fopen(f1, "wb");
        CHECK(f != NULL);
        if (f) {
            fputs("1", f);
            fclose(f);
        }
        f = fopen(f2, "wb");
        if (f) {
            fputs("2", f);
            fclose(f);
        }
        {
            char same[1400];

            snprintf(same, sizeof(same), "%s/mk/a b/../one.txt", tmpl);
            CHECK(plat_same_file(f1, f1) && plat_same_file(f1, same) && !plat_same_file(f1, f2));
        }
        CHECK(plat_is_executable(f1) || !plat_is_executable(f1));               /* (executable bits differ between hosts: only that it does not crash) */
        CHECK(!plat_is_executable(deep) || 1);

        /* a command of the platform's shell, with its output read back (ffmpeg's frames come this way), and one run for its exit status */
        {
            FILE *p = plat_popen_read("echo pentamoor");
            char line[64] = "";

            CHECK(p != NULL);
            if (p) {
                size_t nread = fread(line, 1, sizeof(line) - 1, p);

                line[nread] = 0;
                CHECK(!strncmp(line, "pentamoor", 9));
                plat_pclose(p);
            }
            CHECK(plat_system("exit 0") == 0 && plat_system("exit 3") != 0);
        }

        /* guest memory: a page nothing touched is zero and takes a write; a system call may fill any of it, and write out of it */
        guest_init();
        CHECK(G != NULL && G[0xB0000123u] == 0 && G[0xFFFFFFFFu] == 0);
        G[0xA0000000u] = 5;
        CHECK(G[0xA0000000u] == 5 && G[0xA0000001u] == 0);
        for (k = 0; k < (int)sizeof(chunk); k++)
            chunk[k] = (uint8_t)(k * 7 + 3);
        f = fopen(f1, "wb");
        CHECK(f != NULL && fwrite(chunk, 1, sizeof(chunk), f) == sizeof(chunk));
        if (f)
            fclose(f);
        fd = open(f1, O_RDONLY | O_BINARY);
        CHECK(fd >= 0);
        plat_guest_commit(0xC0FFF000u, sizeof(chunk));                                    /* spans two megabyte chunks on Windows */
        CHECK(fd >= 0 && read(fd, G + 0xC0FFF000u, sizeof(chunk)) == (long)sizeof(chunk));
        CHECK(!memcmp(G + 0xC0FFF000u, chunk, sizeof(chunk)));
        if (fd >= 0)
            close(fd);
        fd = open(f2, O_WRONLY | O_CREAT | O_TRUNC | O_BINARY, 0666);
        plat_guest_commit(0xD1000000u - 100, 200);                                         /* a range that crosses a chunk boundary */
        memcpy(G + 0xD1000000u - 100, chunk, 200);
        CHECK(fd >= 0 && write(fd, G + 0xD1000000u - 100, 200) == 200);
        if (fd >= 0)
            close(fd);
        f = fopen(f2, "rb");
        CHECK(f != NULL && fread(got, 1, 200, f) == 200 && !memcmp(got, chunk, 200));
        if (f)
            fclose(f);
        plat_guest_commit(0xFFFFFF00u, 0x1000);                                              /* past the end of the 32-bit space: clamped, no crash */
    }

    /* a path too deep for the table and one with nothing in it must not crash */
    {
        char deep[800] = "C:";

        for (i = 0; i < 100; i++)
            strcat(deep, "\\d");
        paths_host(deep, 0, out, sizeof(out));
        paths_host("", 0, out, sizeof(out));
        paths_host("C:\\", 0, out, sizeof(out));
        CHECK(1);
    }

    test_rmtree(tmpl);
    printf("test_paths: %d checks, %d failed\n", checks, failures);
    return failures != 0;
}
