# Display: full screen, scaling, filters, the window and its settings

The game draws a fixed picture (1024x768 by default, `PORT_RES` for 640x480 and 800x600: `resolution.md`) and the front end puts it on whatever window or display there is. This note is the design, how the mouse is mapped,
what the keys and files are, and what was run where. The user-facing part is the README's "Display". Code: `src/port/display.c` and `display.h` (pure: modes, layout, mouse mapping, the window to start in, `display.cfg`'s text and
rules, the keys, the controller combination, the on-screen message), `display_cfg.c` (the file on disk), the SDL half in `front_sdl.c` (window, renderer, textures, events), the message drawn in `compose.c`; tests `test_display.c`
(unit, in `make test`) and `tools/display/xe2e.py` (a real X server, below).

## What the player gets

| | |
|---|---|
| **F11**, **Alt+Enter** | borderless full screen (`SDL_WINDOW_FULLSCREEN_DESKTOP`: the display's own size and mode, no mode switch) on and off; leaving puts the window back at its size and place |
| **Ctrl+F11** | scaling `fit` -> `integer` -> `stretch` -> `fit` |
| **Shift+F11** | filter `nearest` -> `linear` -> `sharp` -> `nearest` |
| **L3 + R3** held 1 s (both sticks pressed in) | full screen on and off |
| `PORT_FULLSCREEN`, `PORT_SCALE`, `PORT_FILTER`, `PORT_WINDOW=WxH` | the same settings from the environment; they win over the file and are never written back |
| `port_overlay/display.cfg` | the settings kept between runs |

`fit` is the default scaling, `sharp` the default filter. A key that the display takes is not passed to the game (neither its press nor its release), and the cycling keys show "Scaling: integer, filter: sharp"
for 1.5 s at the top of the screen, drawn by the compositor (`compose.c`, `draw_display_notice`, so a `shot` has it) the way the pad's "(Y/N)" hint is.

### Are the keys free?

Checked three ways. (1) The game's accelerator table (resource 111, `help-about.md`) has F1 (no handler), F12 (the debug flag) and F4 to F11 and letters as debug commands behind that flag, and `TranslateAcceleratorA`
is a stub in this port, so no accelerator works; the table has no Alt+Enter. (2) The lifted code has the constant 0x7a (F11's virtual-key code) in ten places, which read as the letter 'z' in text handling and as pushed arguments, not as a test of a key code
(the key handlers that were found, the map's, compare F1's 0x70, the arrows, Space and Escape: `controller.md`); that is a search, not a proof. (3) Run: on the title screen `Alt+F11` (not ours, so it reaches the game as F11) changes nothing on the screen,
and the input log shows it delivered as `vk 0x7a`; F11, Ctrl+F11, Shift+F11 and Alt+Enter are never delivered (`key vk` lines in `xe2e.py`'s `fullscreen` scenario), a plain Enter still is. Ctrl, Shift and Alt themselves are the game's modifier keys and are passed on as before
(the game reads them with `GetAsyncKeyState`), with one exception: an Alt press is held back until another key, a click or its own release needs it, so that Alt+Enter does not show the game an Alt press (a screen that waits for "any key"
would take it), and a lone Alt tap still arrives as a press and a release. The pad layer never sees the keyboard; the one combination that uses the pad's buttons is below.

### Why L3 + R3, not Back + Start

`pad.c` maps Back to Escape and Start to Enter, each sent when the button goes down. Holding Back and then Start sends Escape and then Enter: on the map Escape asks "Ready to Quit?" and Enter answers its default button, which
quits. So Back + Start is not free. L3 (left stick pressed in) is Space, "stop" on the map, and R3 the fast-cursor modifier: pressing both sends one harmless Space. They are the pair nobody presses by accident for a second.

## The picture

```
game frame (RGB24, SCREEN_W x SCREEN_H)  ->  streaming texture  ->  [sharp: render target, k times larger]  ->  drawable (pixels)  ->  window (points)
```

The renderer's logical size (`SDL_RenderSetLogicalSize`) is not used any more. It did two jobs, scaling and mapping the mouse, and could do neither with a mode of ours (`integer`, `stretch`, a whole-number-or-fractional
rule, a prescale). Both are done by `display_layout` and `display_to_screen` instead, from the sizes SDL reports (`SDL_GetWindowSize`, `SDL_GetRendererOutputSize`), looked at again at every present and every mouse event, so a resize, a move
to another display and a change of display scaling need no event handling of their own.

**Layout** (`display_layout`, all in output pixels): `fit` is the Steam Deck's rule, moved out of `steamdeck.c` (`view_scale` is now a call to `display_fit`, unchanged: its tests in `test_steamdeck.c` are untouched): the largest size with the
shape kept; a whole-number scale when it uses at least 90% of the best fractional one (`INT_SCALE_MIN`), else the fractional one. `integer` is always `floor` of the best scale, with bars (below 1x, where even one copy does not fit, it is the
fractional fit: the picture is never cut). `stretch` is the whole drawable, each axis on its own. The picture is centred; the size is rounded to a whole pixel and never exceeds the drawable.

| Drawable | fit | integer | stretch |
|---|---|---|---|
| 1280x800 (the Deck) | 1024x768, 1x, bars 128/16 | same | 1280x800 |
| 1366x768 | 1024x768 at 171,0 | same | 1366x768 |
| 1920x1080 | 1440x1080, 1.41x | 1024x768, 1x | 1920x1080 |
| 2560x1440 | 1920x1440, 1.88x | 1024x768, 1x | 2560x1440 |
| 3840x2160 | 2880x2160, 2.81x | 2048x1536, 2x | 3840x2160 |
| 2048x1536 (a Retina window of 1024x768 points) | 2048x1536, 2x | same | same |

**Filters**: `nearest` and `linear` are the texture drawn with that sampler (`SDL_SetTextureScaleMode` per draw, so no texture is remade when the filter changes). `sharp` is the sharp-bilinear
look: where the picture lands on a whole number of pixels per pixel on both axes it is `nearest` (exact); otherwise it is first enlarged by `ceil(scale)` (at most 8, and within the renderer's largest texture) with nearest neighbour into a
render target and that is drawn with the linear sampler, so the final step is a reduction by less than one whole step: every pixel edge is blurred by under one output pixel, and nothing shimmers. Below 1x, `sharp` is `linear`.
The render target is made again only when its size changes and filled again only when the frame changes, not at every present (a software renderer, and resizing, stay cheap), and after `SDL_RENDER_TARGETS_RESET` / `SDL_RENDER_DEVICE_RESET`.
Default is `sharp`: it equals `nearest` at the sizes people will mostly see (whole numbers) and does not look torn at the others; the old front end used `nearest` in a window and `linear` in a full screen that was not a whole number, which `sharp` replaces by one rule.

## HiDPI

A Retina Mac window is in points and its drawable is 2x that, which was a mistake before: the window had no `SDL_WINDOW_ALLOW_HIGHDPI`, so macOS drew the 1024x768 picture into a 1024x768-pixel buffer and enlarged it (soft, blurry, with the
filter chosen by the system). Now the window is created with the flag (Cocoa, and Wayland, give a full-resolution drawable; X11 and Windows have one point per pixel unless the system scales), and everything that decides a size uses pixels:

- `display_layout` gets the drawable's size in pixels, so on a 1440x900-point Retina display a window of 1024x768 points is 2048x1536 pixels and the picture is exactly 2x (`whole`: nearest and sharp are exact copies).
- The window it starts as (`display_initial_window`) is the largest whole-number multiple *in pixels* of the picture that fits 90% of the usable area: `dpi` is the drawable's width over the window's (measured on the hidden window just made), so a
  Retina MacBook Air gets 1024x768 points (2x), a 4K display at 200% scaling 1024x768 points as well, a 4K display at 100% gets 2048x1536.
- The minimum window size is the picture at 1x *pixels* (512x384 points on a Retina Mac; 1024x768 elsewhere), capped to the size it started at so a small display (a 1366x768 laptop starts with an 874x655 window) is not given a minimum larger than itself.
- Windows: SDL is asked for per-monitor DPI awareness (`SDL_WINDOWS_DPI_AWARENESS=permonitorv2`; SDL 2.24 and newer read it) so a 150% display is not stretched by the system. Window sizes there are then pixels and `dpi` is 1.
- `shot` is unaffected: it writes the frame as the game composed it.

## The mouse

SDL gives window coordinates in points. `display_to_screen` turns the point's middle into drawable pixels (`(wx + 0.5) * ow / ww`), takes the picture's rectangle off, scales by `sw / dst.w` and floors:

```
px = floor(((wx + 0.5) * ow / ww - dst.x) * sw / dst.w)      py likewise with oh, wh, dst.y, sh, dst.h
```

A point in a bar gives a number outside 0..sw-1 and the call returns 0; the game gets that number as before (SDL's own logical-size mapping did the same), it hits no window. `stretch` has no bars and
maps each axis on its own. Touch is a mouse to SDL and arrives as the same events, so it is mapped the same way (not exercised: no touch screen was available).

**The units of the events (found on the Retina Mac, `front_sdl.c`, "mouse units").** "Window coordinates" are not always points: once an `SDL_Renderer` is attached to a window, SDL (its renderer event watch; sdl2-compat 2.32.72 over SDL3 here) turns the
positions of that window's mouse events into *render pixels* by itself, with or without `SDL_RenderSetLogicalSize`: a click at the point 100 of a 2x window arrives as 200 (a probe pushing events through `SDL_PushEvent` and reading them back showed it:
points on a window without a renderer, pixels with one, logical units with a logical size). Taking the events as points would have put every click at twice its place on a Retina Mac, and the same code is right on X11, where the factor is 1. Which it is depends on the SDL (and its version
and platform), so it is measured instead of assumed: the front end pushes a mouse motion and a button event of its own (`which` = a marker) through the same path at the start and after each size or display change, reads back what position
arrives, and takes `arrived / sent` as the factor the events are multiplied by (1 or the pixels per point). The window's size in the events' unit is `SDL_GetWindowSize * factor`, which is the drawable's own size when they are pixels, and that is what goes to `display_to_screen` (hence its
`double ww, wh`). The same factor undoes the multiplication on scripted positions.

The mapping is applied to `SDL_MOUSEMOTION` and `SDL_MOUSEBUTTON*` in the window loop and nowhere else. Events that a script or `PORT_CONTROL` pushes (`move`, `click`, `down`, `up`) carry a marker in `which` and are given
to the game as they are (less the multiplication): they are already game pixels, which is what a script means, so they are exact at every window size (the old `to_window` inverse, which was off by a pixel in a smaller window, is gone). `wmove X Y` and `wclick X Y`
send positions in *window* coordinates, unmarked, which is how a real mouse event looks to the loop: the tests of the mapping that need no pointer hardware. Real events are checked by `test_display.c` (the round trip of every 5th pixel in 20 window and display shapes, including 2x and 1.25x
scaling, events in points and in pixels, and odd sizes, and that the drawn "Start New Game" button maps back to 528,493), by `hidden_e2e.py` on the Retina Mac (below), and by XTest clicks on a real X server.

## The window

- **Start size**: the saved one (`display.cfg`, or `PORT_WINDOW`), else `display_initial_window`: the largest whole-number multiple of the picture (in pixels) that fits 90% of the display's usable area (`SDL_GetDisplayUsableBounds`: less the menu
  bar, Dock, taskbar), never larger than it; where not even 1x fits, 90% of the area with the shape kept (1366x768 less a taskbar: 874x655; a Deck in desktop mode: 912x684). A saved size is limited to the usable area and
  never below the minimum. A saved position is used only if at least 64x64 points of the window are on some display (`display_pos_ok`), else the window is centred.
- **Resizable** (`SDL_WINDOW_RESIZABLE`), the picture re-fitted at the next present; **minimum** as above; **title** "Pentamoor". The window is created hidden, sized and placed, then shown, so it does not jump. With SDL's dummy or
  offscreen driver (tests, CI) the window stays the screen's size and nothing is saved.
- **Full screen** toggles with `SDL_SetWindowFullscreen(SDL_WINDOW_FULLSCREEN_DESKTOP)` and a minimised-on-focus-loss hint switched off (a full-screen game on one display, Steam's overlay and Gamescope must not minimise it). Before
  entering, the window's size and place are noted (from the move and size events, which are ignored while full screen or maximised and for 1.5 s after leaving, while the window system settles); after leaving, SDL's own restoring is
  repeated for that second if the window system got it wrong. If the player enters or leaves full screen without us (the green button on a Mac, a window manager's key) the state follows what SDL reports.

## display.cfg

Plain text in the overlay folder (`PORT_OVERLAY`, default `port_overlay/`), made if the folder is not there yet, and nowhere else (it is written as `display.cfg.tmp` and renamed). Lines of `key=value`, `#` for comments:

```
fullscreen=0            # 0 or 1 (also yes/no, on/off, true/false)
scale=fit               # fit, integer, stretch
filter=sharp            # nearest, linear, sharp
window=1280x800         # the window's size in points when it is not full screen
position=100,60         # its top-left corner
```

Missing, empty, binary, truncated, outdated (unknown keys, another version) and corrupt files are fine: every line that is understood counts, the rest is skipped, a setting not in the file takes its default (full screen: the Deck's default, a window
elsewhere). A window below 160 or above 16384 points on a side is refused. The environment wins over the file: `display_resolve` is the whole rule (file, then the Deck's full-screen default, then `PORT_FULLSCREEN`, `PORT_SCALE`, `PORT_FILTER`, `PORT_WINDOW`; a bad value is
ignored with a line on stderr). What is written back (`display_cfg_update`): the file as it was read, plus what the player changed in this run (a setting that is not what the run started with: so `PORT_SCALE=stretch` for one run is not remembered, pressing Ctrl+F11 in it is), plus the window's
windowed size and place (not a size that came from `PORT_WINDOW`, unless the player resized it). It is written one second after the last change (so a run that is killed keeps its settings), and when the game ends, also on SIGTERM/SIGINT.

## Tests and what they covered

`make -C src/port test`: `test_display` (about 480 checks: names and cycling, the layout for 1280x800, 1366x768, 1920x1080, 2560x1440, 3840x2160, a Retina window, odd sizes and the three modes, the prescale, the mapping at 20
display and window shapes including 2x, 1.25x and odd sizes, with the events in points and in pixels, the start and minimum window sizes for 15 displays and scaling factors from 1 to 3, the position check, the file's text and every kind of damaged file, saving to a new folder and over
an old file, the environment's precedence and what is written back, the key table, the controller combination's timing (including a clock that wraps), and the message's life), `test_wm` (the message is composed into the frame and expires), `test_steamdeck`
(`view_scale` as it was: the Deck's behaviour is the same, unchanged tests) and the existing suites. On the dummy driver (any machine) the keys, the cycling and the message were driven through `PORT_CONTROL` (`key ctrl+f11`, `key alt+return`, `view`,
`shot`): the layout lines, `shot` at the game size, the message in it, and which keys reached the game.

**A real Retina Mac, with the window never shown** (`tools/display/hidden_e2e.py`, 92 checks, all passing, `PORT_HIDDEN=1`; Apple Silicon, a 1728x1080-point display of 3456x2160 pixels, usable area 1728x988 points, sdl2-compat 2.32.72 over SDL3, the Metal renderer with render-target support):
the window starts at 1024x768 points with a 2048x1536-pixel drawable (2.00 per point, as `display_initial_window` says for that display), the picture is exactly 2x; for fit, integer and stretch and nearest, linear and sharp, in windows of 1024x768, 1500x1000 and 700x525 points
(3000x2000 and 1400x1050 pixels, fractional scales of 2.60 and 1.37 included), what the renderer drew (`winshot`, read back at the drawable's size) matches the game's own frame laid out by an independent computation (exact for nearest and for sharp at a whole-number scale, the sharp
prescale path through a Metal render target included; blurred as it should be for linear), the black bars are black, and clicks sent in window points (`wclick`, through the same path as the real mouse's events, after SDL's own conversion to pixels) reach the game pixel drawn under them
at the four corners and the middle. The same script also passes on runbox under Xvfb (1x, 92 checks). The probe that found the event units and the display's numbers are described above. Before the calibration the same clicks arrived at twice the pixel on this Mac.

`tools/display/xe2e.py` (103 checks, all passing on runbox, x86-64 CachyOS, SDL 2.32.70 as sdl2-compat) runs the real thing on a real X server (Xvfb with `minwm.c`, a window manager of about 150 lines that does what the display needs: EWMH full screen with the old geometry restored, a free area, minimum sizes; `xtool.c` makes real key and pointer
events with XTest and resizes and moves the window like a user). It plays the title screen and checks, against a layout it works out itself and the image of the X screen: the start size on 1280x800, 1920x1080 and 2560x1440 displays; F11 and Alt+Enter in and out, the window's place kept, the keys not reaching the game, a plain Enter and Alt+F11
reaching it; Ctrl+F11 and Shift+F11 through all 3 x 3 modes on a 1920x1080 display (picture position, the X screen against the game's own frame: exact for nearest and sharp at a whole-number scale, and 100% of the pixels
are the game's own colours for nearest at 1.41x against 38% for linear), the message on screen and gone after 1.5 s; resizing to several shapes, a window dragged tiny stopping at the minimum, stretch in an odd window; display.cfg written within seconds, read at the next start,
beaten by the environment and not changed by it, junk and old files, an oversized and off-display saved window; the two-stick combination; and for six setups (windowed, full screen fit, integer and stretch, a stretched odd window, a 4K display) a real
pointer click at the drawn "Start New Game": the game receives 528,493 (within a pixel) and opens the new game screen. In all of them the clicks at the four corners of the picture and its middle reach the game at the pixel drawn under them.

**Not checked, because it could not be on these machines:** a real *visible* Retina window and macOS native full screen with its animation (the green button and Ctrl+Cmd+F toggle SDL's state, which we then follow; the hidden window proved the drawable, the renderer and the mapping, not the Space transition),
classic SDL2 rather than sdl2-compat (the release's macOS build links SDL2 2.32 built from source: the event units are measured, so either should work, but only sdl2-compat was seen), real Wayland (only X11 through Xvfb, with SDL's compatibility layer over SDL3), Windows (the hint for DPI awareness,
`SDL_WINDOW_ALLOW_HIGHDPI` with a 125%/150% display, the D3D renderer with a render target; the unit tests build there in CI and nothing else does), more than one display (the saved-position check is unit tested), a touch screen, a real controller (the combination is driven with `pad` events),
and sound and video playing through a mode change.
