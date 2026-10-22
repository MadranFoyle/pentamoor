/* test_regstore.c - the file registry (regstore.c): what it keeps and what it refuses, the file format, a write that survives a reopen, a file that is damaged, a folder that cannot be
 * written. Pure: no game, and the values are made up (nothing here is a value the game reads or writes).
 *   make -C src/port test */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "regstore.h"
#include "test_util.h"

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

#define MP "HKLM\\SOFTWARE\\MicroProse\\Test Product"
#define WIN REGSTORE_WINDOWS_KEY

static void write_file(const char *path, const char *text)
{
    FILE *f = fopen(path, "wb");

    if (f) {
        fputs(text, f);
        fclose(f);
    }
}

static int read_file(const char *path, char *out, size_t cap)
{
    FILE *f = fopen(path, "rb");
    size_t n;

    if (!f)
        return -1;
    n = fread(out, 1, cap - 1, f);
    out[n] = 0;
    fclose(f);
    return (int)n;
}

static int has(const char *key, const char *name, uint32_t type, const char *bytes, uint32_t len)
{
    uint32_t t, l;
    const uint8_t *d;

    return regstore_get(key, name, &t, &d, &l) && t == type && l == len && !memcmp(d, bytes, len);
}

static void test_what_it_keeps(void)
{
    CHECK(regstore_keeps(MP, "x") && regstore_keeps("HKLM\\SOFTWARE\\MicroProse", "x") && regstore_keeps("hklm\\software\\microprose\\a\\b", "x"));
    CHECK(!regstore_keeps("HKLM\\SOFTWARE\\MicroProseX", "x") && !regstore_keeps("HKLM\\SOFTWARE", "x"));
    /* the Magic Shell keeps its page settings under the current user's MicroProse key */
    CHECK(regstore_keeps("HKCU\\Software\\MicroProse\\Magic: The Gathering\\DuelOptions", "Layout") && regstore_keeps("HKCU\\SOFTWARE\\MicroProse", "x"));
    CHECK(!regstore_keeps("HKCU\\SOFTWARE\\MicroProseX", "x") && !regstore_keeps("HKCU\\SOFTWARE\\Other", "x") && !regstore_keeps("HKCU\\SOFTWARE", "x") && !regstore_keeps("HKCR\\SOFTWARE\\MicroProse", "x"));
    CHECK(regstore_keeps(WIN, "FirstInstallDateTime") && regstore_keeps(WIN, "ProductId") && regstore_keeps(WIN, "productid"));
    CHECK(!regstore_keeps(WIN, "RegisteredOwner") && !regstore_keeps(WIN, "Version"));         /* of Windows' key only the two values */
    CHECK(!regstore_keeps("HKLM\\SOFTWARE\\Microsoft", "ProductId") && !regstore_keeps(NULL, "x") && !regstore_keeps("", "x"));
}

static void test_no_store(void)
{
    uint32_t t, l;
    const uint8_t *d;

    regstore_open(NULL);
    CHECK(!regstore_enabled());
    CHECK(regstore_put(MP, "Value", 3, (const uint8_t *)"ab", 2) == -1);               /* nothing is kept without a store */
    CHECK(!regstore_get(MP, "Value", &t, &d, &l) && !regstore_key_exists("HKLM\\SOFTWARE"));
    CHECK(regstore_open("") == 0 && !regstore_enabled());
}

static void test_write_and_reopen(void)
{
    char dir[600], path[700], text[2000];
    const uint8_t dword[4] = {1, 0, 0, 0};
    const uint8_t blob[12] = {0xde, 0xad, 0xbe, 0xef, 0, 1, 2, 3, 0xff, 0x10, 0x20, 0x30};

    test_tmpdir(dir, sizeof(dir), "regstore_");
    CHECK(dir[0] != 0);
    snprintf(path, sizeof(path), "%s/registry.dat", dir);

    CHECK(regstore_open(path) == 0 && regstore_enabled() && !strcmp(regstore_path(), path));      /* no file yet: an empty store */
    CHECK(read_file(path, text, sizeof(text)) < 0);                                              /* ... and opening it made no file */
    CHECK(regstore_put(MP, "Blob", 3, blob, 12) == 0);
    CHECK(regstore_put(MP, "Result", 4, dword, 4) == 0);
    CHECK(regstore_put(WIN, "ProductId", 1, (const uint8_t *)"11111-OEM-0000000-22222", 24) == 0);
    CHECK(regstore_put("HKLM\\SOFTWARE\\Other", "Blob", 3, blob, 12) == -1);                      /* a key it does not keep */
    CHECK(regstore_put(WIN, "RegisteredOwner", 1, (const uint8_t *)"x", 2) == -1);
    CHECK(regstore_put(MP, "Tab\tName", 3, blob, 1) == -1 && regstore_put(MP, "Line\nName", 3, blob, 1) == -1 && regstore_put(MP, "", 3, blob, 1) == -1);
    CHECK(regstore_put(MP, "Big", 3, blob, REGSTORE_MAX_DATA + 1) == -1 && regstore_put(MP, "NoData", 3, NULL, 4) == -1);
    CHECK(has(MP, "Blob", 3, (const char *)blob, 12) && has(MP, "BLOB", 3, (const char *)blob, 12) && has("hklm\\software\\microprose\\test product", "blob", 3, (const char *)blob, 12));
    CHECK(regstore_key_exists("HKLM\\SOFTWARE\\MicroProse") && regstore_key_exists(MP) && regstore_key_exists("HKLM\\SOFTWARE") && regstore_key_exists("HKLM"));
    CHECK(!regstore_key_exists(MP "\\Sub") && !regstore_key_exists("HKLM\\SOFTWARE\\Micro") && !regstore_key_exists("HKCU"));

    /* the file: a header, then one value a line, key TAB name TAB type TAB hex */
    CHECK(read_file(path, text, sizeof(text)) > 0);
    CHECK(!strncmp(text, "# pentamoor registry 1\n", 23));
    CHECK(strstr(text, MP "\tBlob\t3\tdeadbeef00010203ff102030\n") != NULL);
    CHECK(strstr(text, MP "\tResult\t4\t01000000\n") != NULL);
    CHECK(strstr(text, WIN "\tProductId\t1\t") != NULL);

    /* reopened: the same values; a second put replaces */
    CHECK(regstore_open(path) == 3);
    CHECK(has(MP, "Blob", 3, (const char *)blob, 12) && has(MP, "Result", 4, (const char *)dword, 4) && has(WIN, "ProductId", 1, "11111-OEM-0000000-22222", 24));
    CHECK(regstore_put(MP, "result", 4, (const uint8_t *)"\x02\0\0\0", 4) == 0);
    CHECK(regstore_open(path) == 3 && has(MP, "Result", 4, "\x02\0\0\0", 4));
    CHECK(regstore_put(MP, "Empty", 3, NULL, 0) == 0 && regstore_open(path) == 4 && has(MP, "Empty", 3, "", 0));

    /* closing forgets */
    regstore_open(NULL);
    CHECK(!has(MP, "Blob", 3, (const char *)blob, 12));

    test_rmtree(dir);
}

static void test_damaged_files(void)
{
    char dir[600], path[700], text[2000];

    test_tmpdir(dir, sizeof(dir), "regstore_");
    snprintf(path, sizeof(path), "%s/registry.dat", dir);
    write_file(path,
               "# pentamoor registry 1\n"
               "\n"
               MP "\tGood\t3\t0a0b\n"
               "no tabs at all\n"
               MP "\tShort\t3\n"
               MP "\tOdd\t3\t0a0\n"                                  /* an odd number of digits */
               MP "\tNotHex\t3\t0g\n"
               MP "\tBadType\tx\t0a\n"
               "HKLM\\SOFTWARE\\Elsewhere\tValue\t3\t0a\n"          /* a key the store does not keep */
               WIN "\tVersion\t1\t41\n"                              /* a value of Windows' key it does not keep */
               MP "\tUpper\t3\tABCD\r\n"                             /* upper-case digits and a Windows line end are read */
               MP "\tGood\t3\t0c\n");                                /* a later line replaces an earlier one */
    CHECK(regstore_open(path) == 3);                               /* Good, Upper, and Good again */
    CHECK(has(MP, "Good", 3, "\x0c", 1) && has(MP, "Upper", 3, "\xab\xcd", 2));
    CHECK(!has(MP, "Short", 3, "", 0) && !has(MP, "Odd", 3, "", 0) && !has(MP, "NotHex", 3, "", 0) && !has(WIN, "Version", 1, "A", 1));
    CHECK(!regstore_key_exists("HKLM\\SOFTWARE\\Elsewhere"));
    /* a write rewrites the file without what was dropped */
    CHECK(regstore_put(MP, "New", 3, (const uint8_t *)"\x01", 1) == 0);
    CHECK(read_file(path, text, sizeof(text)) > 0 && !strstr(text, "no tabs") && !strstr(text, "Elsewhere") && !strstr(text, "NotHex") && strstr(text, "\tNew\t3\t01\n"));

    /* a line longer than any value can make is skipped, the next one is read */
    {
        char *big = malloc(40000);

        memset(big, 'a', 39999);
        big[39999] = 0;
        snprintf(text, sizeof(text), "%s", "# pentamoor registry 1\n");
        write_file(path, text);
        {
            FILE *f = fopen(path, "ab");

            fprintf(f, MP "\tHuge\t3\t%s\n" MP "\tAfter\t3\t01\n", big);
            fclose(f);
        }
        free(big);
        CHECK(regstore_open(path) == 1 && has(MP, "After", 3, "\x01", 1));
    }
    /* binary rubbish is not a registry */
    write_file(path, "\x01\x02\x03\x00\xff\xfe garbage\n\t\t\t\n");
    CHECK(regstore_open(path) == 0 && regstore_enabled());

    test_rmtree(dir);
}

static void test_limits_and_failure(void)
{
    char dir[600], path[700], name[40];
    int i;

    test_tmpdir(dir, sizeof(dir), "regstore_");
    snprintf(path, sizeof(path), "%s/registry.dat", dir);
    CHECK(regstore_open(path) == 0);
    for (i = 0; i < REGSTORE_MAX_VALUES; i++) {
        snprintf(name, sizeof(name), "V%d", i);
        CHECK(regstore_put(MP, name, 4, (const uint8_t *)"\0\0\0\0", 4) == 0);
    }
    CHECK(regstore_put(MP, "OneTooMany", 4, (const uint8_t *)"\0\0\0\0", 4) == -1);
    CHECK(regstore_put(MP, "V0", 4, (const uint8_t *)"\1\0\0\0", 4) == 0);                    /* replacing is not adding */
    CHECK(regstore_open(path) == REGSTORE_MAX_VALUES);

    /* a folder that is not there: the value is refused (-2) and not kept */
    snprintf(path, sizeof(path), "%s/no/such/folder/registry.dat", dir);
    CHECK(regstore_open(path) == 0 && regstore_enabled());
    CHECK(regstore_put(MP, "Lost", 4, (const uint8_t *)"\0\0\0\0", 4) == -2);
    CHECK(!has(MP, "Lost", 4, "\0\0\0\0", 4));

    regstore_open(NULL);
    test_rmtree(dir);
}

int main(void)
{
    test_what_it_keeps();
    test_no_store();
    test_write_and_reopen();
    test_damaged_files();
    test_limits_and_failure();
    printf("test_regstore: %d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}
