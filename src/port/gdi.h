/* gdi.h - what the window manager needs of the graphics layer (gdi.c): device contexts, window surfaces, the object table. */
#ifndef PORT_GDI_H
#define PORT_GDI_H

#include <stdint.h>

#include "wm.h"

enum { GDI_CURSOR = 1, GDI_ICON, GDI_ACCEL, GDI_BRUSH, GDI_PEN, GDI_FONT, GDI_PALETTE, GDI_BITMAP, GDI_REGION, GDI_MENU };

uint32_t gdi_new_object(int kind, uint32_t a, uint32_t b);
int gdi_object_kind(uint32_t h);
uint32_t gdi_object_a(uint32_t h);
uint32_t gdi_object_b(uint32_t h);

uint32_t gdi_color_query_dc(void);
void gdi_color_query_result(uint32_t hdc, uint32_t brush, uint8_t fg[3], uint8_t bg[3], int *transparent, int *has_bg);
uint32_t gdi_window_dc(uint32_t hwnd);           /* a device context drawing on the window's client area */
void gdi_resize_surface(Window *w);
void gdi_release_surface(Window *w);
void gdi_clear_surface(Window *w);               /* an owner-draw button is repainted on a clean surface */
void gdi_forget_texts(Window *w);
uint32_t gdi_set_dibits_to_device(const uint32_t *a);   /* SetDIBitsToDevice (12 arguments) */
/* WM_ERASEBKGND (hdc 0: with a new DC); a window that answers "erased" without drawing is see-through */
uint32_t gdi_send_erase(Window *w, uint32_t hdc);
int gdi_erase_background(Window *w);             /* fill the client area with the class brush: 1 if there was one */

/* movie windows (the game's MCI window class) */
uint32_t wm_movie_message(Window *w, uint32_t msg, uint32_t wp, uint32_t lp);
void wm_movie_release(Window *w);
uint32_t wm_desktop(void);
uint32_t wm_main_hwnd(void);
uint32_t wm_key_target(void);
uint32_t wm_held_clip(void);       /* the window of a clip that waits, undrawn, for a key or a click (0: none) */
uint32_t wm_class_background(const Window *w);
void wm_quit_all(int code);
uint32_t wm_desktop_hwnd(void);
uint32_t wm_top_dialog(void);
void wm_popup_geometry(int li, int *x, int *y, int *w, int *h);
int wm_popup_levels(void);
int wm_popup_row(int li, int i, const char **text, uint32_t *flags, int *y0, int *y1, int *hot);
int wm_dialog_count(void);
uint32_t wm_dialog_at(int i);

#endif
