/* modules.c - LoadLibraryA and GetProcAddress: the game's DLLs. A DLL whose machine code tools/lift/gen_dll.py lifted is mapped at the base it was
 * lifted for and run (its DllMain, its exports); a library the host provides instead (sound.c: MAGSND.DLL, which needs DirectSound) is a table of C functions. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "port.h"

#define P(a) (G + (uint32_t)(a))

typedef struct HostModule {
    const char *name;                   /* "magsnd.dll" */
    uint32_t handle;
    const HostExport *exports;
    uint32_t addr[64];                  /* the guest address handed out for each export, once asked for */
} HostModule;

static HostModule host_modules[4];
static int nhost_modules;
static uint32_t next_host_handle = 0x7E000000u;

void module_register_host(const char *name, const HostExport *exports)
{
    HostModule *h = &host_modules[nhost_modules++];

    h->name = name;
    h->handle = next_host_handle;
    next_host_handle += 0x10000;
    h->exports = exports;
}

/* the module name as it is compared: the file part, lower case, with ".dll" */
static void key_of(const char *name, char *out, size_t cap)
{
    const char *base = name, *p;
    size_t n;

    for (p = name; *p; p++)
        if (*p == '\\' || *p == '/' || *p == ':')
            base = p + 1;
    n = strlen(base);
    if (n >= cap - 5)
        n = cap - 6;
    memcpy(out, base, n);
    out[n] = 0;
    if (!strchr(out, '.'))
        strcat(out, ".dll");
    for (p = out; *p; p++)
        out[p - out] = (char)((*p >= 'A' && *p <= 'Z') ? *p + 32 : *p);
}

static uint32_t loaded_base[8];
static const LiftModule *loaded_mod[8];
static int attached[8];
static int nloaded_mods;

const char *module_file(uint32_t hmod)
{
    int i;
    static char name[80];

    for (i = 0; i < nloaded_mods; i++)
        if (loaded_base[i] == hmod) {
            size_t k;

            snprintf(name, sizeof(name), "%s", loaded_mod[i]->name);
            for (k = 0; name[k]; k++)
                if (name[k] >= 'a' && name[k] <= 'z')
                    name[k] = (char)(name[k] - 32);
            return name;
        }
    return NULL;
}

uint32_t module_find(const char *name)
{
    char key[80];
    int i;

    key_of(name, key, sizeof(key));
    for (i = 0; i < nhost_modules; i++)
        if (!strcmp(host_modules[i].name, key))
            return host_modules[i].handle;
    for (i = 0; i < nloaded_mods; i++)
        if (!strcmp(loaded_mod[i]->name, key))
            return loaded_base[i];
    return 0;
}

/* Map a lifted library (once); its DllMain runs when it is attached. */
static uint32_t module_map(const char *name)
{
    char key[80], guest[300], host[1200];
    uint32_t h = module_find(name);
    int i;
    Image img;

    if (h)
        return h;
    key_of(name, key, sizeof(key));
    for (i = 0; lift_game->modules[i]; i++)
        if (!strcmp(lift_game->modules[i]->name, key))
            break;
    if (!lift_game->modules[i]) {
        port_log("LoadLibraryA(%s) -> not found (no host version and none lifted)", name);
        return 0;
    }
    if (strpbrk(name, "\\/:"))
        snprintf(guest, sizeof(guest), "%s", name);
    else
        snprintf(guest, sizeof(guest), "%s\\%s", "C:\\Magic\\Program", name);
    if (!paths_host(guest, 0, host, sizeof(host)) || pe_load_module(host, lift_game->modules[i]->base, &img) != 0) {
        port_log("LoadLibraryA(%s) -> the file is not there", name);
        return 0;
    }
    port_log("LoadLibraryA(%s) -> mapped at 0x%08x", name, img.base);
    loaded_base[nloaded_mods] = img.base;
    loaded_mod[nloaded_mods++] = lift_game->modules[i];
    if (!strcmp(key, "deckdll.dll"))
        lzw_install_deckdll(img.base);     /* its picture decompressor is the game's hand-written one too */
    return img.base;
}

static void attach(int i)
{
    uint32_t args[3] = {loaded_base[i], 1, 0};              /* DllMain(hinst, DLL_PROCESS_ATTACH, 0) */

    attached[i] = 1;
    guest_call(loaded_mod[i]->entry, 3, args);
}

void module_attach(void)
{
    int i;

    for (i = 0; i < nloaded_mods; i++)
        if (!attached[i])
            attach(i);
}

uint32_t module_load(const char *name)
{
    uint32_t h = module_map(name);
    int i;

    for (i = 0; h && i < nloaded_mods; i++)
        if (loaded_base[i] == h && !attached[i])
            attach(i);
    return h;
}

/* An import the loader binds (pe.c): if the library is one that was lifted, map it and give the address of the export. */
uint32_t module_import(const char *dll, const char *name)
{
    char key[80];
    int i;
    uint32_t h;

    key_of(dll, key, sizeof(key));
    for (i = 0; lift_game->modules[i]; i++)
        if (!strcmp(lift_game->modules[i]->name, key))
            break;
    if (!lift_game->modules[i])
        return 0;
    h = module_map(dll);
    return h ? pe_export(h, name) : 0;
}

uint32_t module_proc(uint32_t hmod, const char *name)
{
    int i;
    uint32_t a;

    for (i = 0; i < nhost_modules; i++)
        if (host_modules[i].handle == hmod) {
            HostModule *m = &host_modules[i];
            const HostExport *e;
            int k = 0;

            for (e = m->exports; e->name; e++, k++)
                if (!strcmp(e->name, name) || (name[0] == '#' && e->ordinal == atoi(name + 1))) {
                    if (!m->addr[k])
                        m->addr[k] = port_host_function(e->fn);
                    return m->addr[k];
                }
            port_log("GetProcAddress(%s, %s) -> not found", m->name, name);
            return 0;
        }
    a = pe_export(hmod, name);
    if (!a)
        port_log("GetProcAddress(0x%x, %s) -> not found", hmod, name);
    return a;
}
