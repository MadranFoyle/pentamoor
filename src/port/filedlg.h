/* filedlg.h - the common file dialogs (GetOpenFileNameA, GetSaveFileNameA): the path and filter logic, which the tests check, and the dialog (filedlg.c). */
#ifndef PORT_FILEDLG_H
#define PORT_FILEDLG_H

#include <stddef.h>

typedef struct FdFilter {
    char desc[160];       /* "Deck files (*.dck)" */
    char pat[160];        /* "*.dck" or "*.dck;*.txt" */
} FdFilter;

/* OPENFILENAME's lpstrFilter: pairs of description and pattern, each ended by a NUL, the whole by an empty string. `s` is a host copy of at most `cap` bytes.
 * Returns how many pairs went into `out` (at most `max`). */
int fd_parse_filter(const char *s, size_t cap, FdFilter *out, int max);

int fd_has_wild(const char *s);                                     /* a '*' or '?' in it */
int fd_wild_match(const char *pattern, const char *name);           /* one pattern, '*' and '?', without regard to case; "*.*" is every name */
int fd_filter_match(const char *patterns, const char *name);        /* patterns separated by ';' */

/* Guest paths: backslashes, "C:\..." (the form paths.c maps). */
void fd_name_of(const char *path, char *out, size_t cap);           /* what follows the last backslash or slash */
void fd_dir_of(const char *path, char *out, size_t cap);            /* what precedes it ("C:\" for a file in the drive's root) */
int fd_parent(const char *dir, char *out, size_t cap);              /* the folder above (1), or 0 if `dir` is a drive's root */
void fd_join(const char *dir, const char *name, char *out, size_t cap);
/* What the user typed, as a full normalized path: an absolute one stays, a relative one is looked for in `cur`; ".." and "." are resolved; quotes and
 * surrounding blanks and a trailing backslash are dropped. */
void fd_resolve(const char *cur, const char *typed, char *out, size_t cap);
int fd_has_ext(const char *name);                                   /* a '.' in the file name (the last component) */
void fd_add_defext(char *path, size_t cap, const char *defext);     /* lpstrDefExt: appended (with a '.') to a name that has no extension */
void fd_offsets(const char *path, int *file_offset, int *file_extension);   /* nFileOffset, nFileExtension (0: no extension) */

#endif
