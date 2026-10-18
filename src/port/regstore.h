/* regstore.h - the registry the runtime keeps on disk: a few values the programs of Spells of the Ancients read and (the installer's licence step) write.
 *
 * The runtime has no registry. winsys.c answers the two Windows values the game asks for (FirstInstallDateTime, ProductId) with fixed ones, and a write used to go nowhere. This store is
 * the small part that is kept: a text file in the install's overlay (port_overlay_sota/registry.dat; regstore_open is given the path), read at start and rewritten whole by every write.
 * It keeps only
 *     the values of keys at or below  HKLM\SOFTWARE\MicroProse
 *     the two values  FirstInstallDateTime  and  ProductId  of  HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion
 * and nothing else: every other key stays "not found" and a write to one goes nowhere, as before. With no store opened (a 1.0 run, a test) nothing is kept at all.
 *
 * The file is documented in docs/notes/sota-licence.md ("The registry file"): a first line "# pentamoor registry 1", then one value a line,
 *     <key>TAB<name>TAB<type>TAB<hex>
 * with the key as a path from the root ("HKLM\SOFTWARE\..."), the type the registry's number (1 string, 3 binary, 4 DWORD) and the bytes in lower-case hex. Lines that start with # and
 * blank lines are skipped; a line that is not of that form, or names a key or value the store does not keep, is dropped when the file is read (and not written back). Keys and names are
 * compared without regard to case, as Windows does.
 */
#ifndef PORT_REGSTORE_H
#define PORT_REGSTORE_H

#include <stddef.h>
#include <stdint.h>

#define REGSTORE_WINDOWS_KEY "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion"
#define REGSTORE_MICROPROSE_KEY "HKLM\\SOFTWARE\\MicroProse"
#define REGSTORE_MAX_VALUES 64
#define REGSTORE_MAX_DATA 1024

/* Open the store at `path` (NULL closes it and forgets the values). A file that is not there is an empty store, made by the first write. Returns the number of values read; a file that
 * cannot be read is an empty store too (0). */
int regstore_open(const char *path);
int regstore_enabled(void);
const char *regstore_path(void);

/* Does the store keep this key (a path from the root) and value? `name` NULL asks about the key alone. */
int regstore_keeps(const char *key, const char *name);
/* Is `key` a key the store holds a value of, or a key on the way to one (HKLM\SOFTWARE is, when HKLM\SOFTWARE\MicroProse\x has a value)? */
int regstore_key_exists(const char *key);
/* The value: 1 and its type, a pointer to its bytes (valid until the next put) and their count, or 0 when there is none. */
int regstore_get(const char *key, const char *name, uint32_t *type, const uint8_t **data, uint32_t *len);
/* Set a value and rewrite the file. 0 on success; -1 for a key or value the store does not keep, no store open, a name with a tab or a line break, too much data or too many values;
 * -2 when the file could not be written (the value is then not kept either). */
int regstore_put(const char *key, const char *name, uint32_t type, const uint8_t *data, uint32_t len);

#endif
