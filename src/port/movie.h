/* movie.h - the AVI movies (movie.c): decoding, and windows that play them. */
#ifndef PORT_MOVIE_H
#define PORT_MOVIE_H

#include <stddef.h>
#include <stdint.h>

#include "wm.h"

typedef struct Movie Movie;

Movie *movie_open(const char *host_path);                          /* NULL if the file is not a movie this host can play */
Movie *movie_open_mem(uint8_t *data, size_t len, const char *path); /* takes the buffer; `path` is for ffmpeg (Indeo 4), may be "" */
void movie_close(Movie *m);
int movie_width(const Movie *m);
int movie_height(const Movie *m);
int movie_frames(const Movie *m);
double movie_fps(const Movie *m);
void movie_frame(Movie *m, int index, uint8_t *rgb);               /* w*h*3 bytes, top row first */
int16_t *movie_audio(const Movie *m, uint32_t *frames, uint32_t *rate, int *channels);   /* malloc'd 16 bit PCM or NULL */
void movie_decode_msvc16(const uint8_t *buf, size_t n, int w, int h, uint16_t *pix);

Window *movie_window(const char *cname, uint32_t parent, uint32_t style, int x, int y, Movie *movie);
int movie_window_playing(Window *w);
void movie_window_play(Window *w);
void movie_window_stop(Window *w);
void movie_window_set_held(Window *w, int on);                      /* an ended see-through clip the game has "painted over": not drawn, but its window stays and takes clicks and keys */
int movie_window_held(const Window *w);
void movie_tick(void);
void movie_window_set_transparent(Window *w, int on);               /* black is see-through (SetVidTransparency) */
const uint8_t *movie_window_alpha(const Window *w);                /* w*h, 0 where see-through, or NULL if the window is opaque */
void movie_window_move(Window *w, int x, int y);                   /* SetVidPos: the window's corner on the screen */
void movie_key_alpha(const uint8_t *rgb, size_t pixels, uint8_t *alpha);

#endif
