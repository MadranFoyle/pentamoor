# Steam Deck

The Steam Deck (SteamOS 3: Arch-based, x86-64, a 1280x800 screen, a read-only root file system with no C compiler or `make`, Python 3 and SDL2 present, a built-in game controller, KDE in desktop mode and
Gamescope in Game mode) is a release target of its own: `pentamoor-<version>-steamdeck.tar.gz`. **Nothing here has been run on a real Deck.** What was run is listed under "Checked", what was not under
"Not verified" (that list is what someone with a Deck has to go through). The files are in `tools/steamdeck/` and the C is `src/port/steamdeck.c`, `textin.c`, `textfocus.c` and `front_sdl.c`.

## For a person with a Deck

1. Download `pentamoor-<version>-steamdeck.tar.gz` (in desktop mode: Steam button > Power > Switch to Desktop; the browser is Firefox). Unpack it where it is to stay, for example `~/Games` (Ark: right-click > Extract here).
   The game is built into the folder and runs from it; the Steam shortcut points at it.
2. Double-click **Install Pentamoor** in the unpacked folder. If it asks what to do with the file instead, right-click it > Properties > Permissions > tick "Is executable" (an archive made by Ark keeps the bit, so this should not be needed). A window asks for the disc
   image (your own `.iso` of the retail CD, version 1.0), then shows a progress bar for 2 to 15 minutes. It needs about 1.2 GB free while it works (about 0.9 GB stay: the game's files 270 MB, the three game modules
   70 MB, and the C compiler it downloads: SteamOS has none, so Zig, about 100 MB to download and 570 MB on disk with its cache, in `tools/local/`). Nothing outside the folder is changed (the root file system is read-only and is not touched).
3. When it says it is installed, answer yes to "Add Pentamoor to Steam". If Steam is running it asks to close it (Steam writes its game list again when it quits, which would undo the change). This writes a shortcut
   into Steam's list of non-Steam games, a menu entry (`~/.local/share/applications/pentamoor.desktop`) and, optionally, the controller layout below.
4. Switch back to Gaming Mode (Steam starts again by itself): Pentamoor is in the Library, under All Games (and "Non-Steam"). Open its page, press the controller button (or the gear > Controller Settings)
   and choose a layout (next section). Then play.
5. The game starts full screen by itself. The mouse is the two trackpads and the touch screen; the controller is described in [controller.md](controller.md). Steam + X brings up Steam's on-screen keyboard (the new
   game's name box also asks for it by itself, see "Text").

Without the window installer: `./pentamoor-install "path/to/disc.iso"` in a terminal (Konsole), then `python3 tools/steamdeck/add-to-steam.py` (add `--desktop-entry --controller-template`; `--help`).
`pentamoor` itself, started from a menu with no game installed in desktop mode, opens the window installer.

## The controller layout

The game takes a pad through SDL's game controller API (`pad.c`: the left stick is the cursor, A and B click, and so on). Steam Input decides what a non-Steam game sees of the Deck: by default the **Desktop**
layout, which makes the Deck a keyboard and mouse (SDL then sees no game controller, so `pad.c` has nothing to read; the Deck still plays as a mouse and keyboard, which the game always supported: trackpads
are the mouse, the Desktop layout's A/B/D-pad send Enter, Esc and arrows; not tried). To make the Deck a game controller choose Steam's **Gamepad** template for Pentamoor:

1. Game mode: Library > Pentamoor > the controller icon (some versions: the gear > Controller Settings) > "Current Layout" (shown as the name of the layout) > Templates.
2. Pick **Gamepad with Mouse Trackpad** (the right trackpad moves the mouse; Pentamoor takes the cursor back to the stick whenever you use it, and gives it to the mouse the moment the mouse moves) or
   plain **Gamepad**. Apply. (Names as remembered from SteamOS 3.5; the list differs between versions. Anything that says Gamepad and keeps A B X Y, the sticks, the triggers, the bumpers, D-pad, View and Menu
   as the Xbox buttons does.)
3. Optional, **unverified**: the layout shipped here. `add-to-steam.py --controller-template` (the window installer offers it) copies `tools/steamdeck/controller_neptune_pentamoor.vdf` into
   `<Steam>/controller_base/templates/`; after a Steam restart it should be in the same Templates list as "Pentamoor": Gamepad with both trackpads as a mouse (left: right click, right: left click).
   If Steam does not list it or it misbehaves, use the built-in template in step 2; nothing else depends on this file.

What the layout must give (what `pad.c` reads, `controller.md` has what each does): A B X Y; both sticks and their clicks; both triggers as analog triggers; both bumpers; the D-pad; View (back) and Menu (start). The
back grips and the trackpad touches are not used.

SDL's own pieces, which need nothing from us: Steam launches a non-Steam game with `SDL_GAMECONTROLLERCONFIG` set for the virtual "Steam Virtual Gamepad" (an Xbox 360 pad as far as SDL is concerned); the
SDL reads it when the controller subsystem starts, as for any SDL program (the front end does not touch it), and `SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS` is set on a Deck
(`front_sdl.c`: the pad keeps working while Steam's overlay, a notification or Gamescope itself has the focus).

## What the program does on a Deck

All of it only on a Deck or Gamescope (`src/port/steamdeck.c`, `deck_here`: env `SteamDeck=1`, which Steam sets for the games it starts on a Deck; `ID=steamos`, `NAME` containing "SteamOS" or
`VARIANT_ID=steamdeck` in `/etc/os-release`; env `GAMESCOPE_WAYLAND_DISPLAY` set, or `XDG_CURRENT_DESKTOP` naming `gamescope`). `PORT_STEAMDECK=1` says it is one (Bazzite, ChimeraOS, a handheld PC),
`PORT_STEAMDECK=0` that it is not.

| What | On a Deck | Elsewhere |
|---|---|---|
| Window | full screen (`SDL_WINDOW_FULLSCREEN_DESKTOP`: the display's own size and mode, no mode switch); `PORT_FULLSCREEN=0` turns it off | a window, as before; `PORT_FULLSCREEN=1` full screen |
| Scaling in full screen | `view_scale`: the screen (1024x768) is scaled with its 4:3 shape kept; a whole-number scale when it uses at least 90% of the best scale, else the fractional one smoothed (linear). 1280x800: 1x, the picture 1024x768 with bars 128 px at the sides and 16 above and below, every pixel square. A 1080p television (docked): 1.41x, 1440x1080. 4K: 2.81x. `PORT_RES=640x480`: 1.67x | the same function whenever it is full screen; a window keeps the nearest-neighbour scale it had |
| Mouse and touch | screen pixels through `SDL_RenderSetLogicalSize` (and `SDL_RenderSetIntegerScale` when whole-number), so a click lands where it is drawn in the bars' offset too | unchanged |
| Pad while another window has the focus | `SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS` | `PORT_PAD_BACKGROUND=1` |
| Minimise on focus loss (full screen) | off (`SDL_HINT_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0`) | the same when full screen |
| SDL text input (what brings Steam's keyboard up) | on only while a text field has the focus (below) | always on, as before (`PORT_TEXTINPUT=auto` makes it follow the focus anywhere) |

## Text

The game reads typed text in two ways. Its own text boxes (the new game's name) read `WM_KEYDOWN` with a scan code and turn it into a character themselves (the Shift they look at is `GetAsyncKeyState`); they
**ignore `WM_CHAR`** (found by sending `key a` with no character: "Melody Whispa" appeared; sending the key and its character typed one `b`, not two). The port's own edit boxes (the file dialogs') and the
duel's prompt bar read `WM_CHAR`. Real keys carry both, so a keyboard, and Steam's keyboard when it sends key events (Steam + X types real key events, as `controller.md` found) work as they always did.

What changed (`front_sdl.c`, `textin.c`, tests in `test_steamdeck.c` and `test_wm.c`):

- **Text with no key** (`SDL_TEXTINPUT` that no `SDL_KEYDOWN` came with: an input method, a paste, an on-screen keyboard that sends text, a key we have no mapping for) used to be dropped. `handle_text` turns it into the
  key presses that type it on a US keyboard (Shift pressed around capitals and shifted punctuation unless the player already holds it), once per character; Latin-1 letters no US key types go as `WM_CHAR` alone
  (`front_push_char`, `wm_inject_char`). Anything else (the euro sign, emoji) is skipped. `PORT_SCRIPT`/`PORT_CONTROL` has `ime TEXT` for it.
- **Exactly once**: a key that is waiting for its own text takes it (as before, `textin_attach`: one printable ASCII character) and nothing more is typed; text with nothing waiting is typed; a key whose text does
  not follow (SDL text input off) gets its character from the US layout instead of waiting (`textin_char_for_key`). Checked with real X key events (below).
- **When is a text field focused?** An EDIT control that is shown and enabled in the modal dialog that is open (`wm_text_focus`: the file dialogs), or the game's name box. The name box is not a window: the game draws
  and reads it in the loop of `Pic_Load_namepick` (0x47be64..0x47c07f), which pops its own key queue with FUN_004080b2 (0x4080b2) on every pass. A hook before that call (`textfocus.c`) notes it when the return
  address is inside that loop; `text_wanted_rule` counts it as the focus for 400 ms after the last note. `SDL_StartTextInput` / `SDL_StopTextInput` follow that (on a Deck): on at the name box, off on the map.
  `PORT_TEXT_LOG=1` prints each change, `textinput` in `PORT_CONTROL` the state.
- Other places the game takes typed text (a saved game's name, a deck's name through the file dialog, the Gauntlet or duel names) were not looked for one by one; the file dialogs are covered by `wm_text_focus`.

## Checked (on this Mac and on `runbox`, a headless x86-64 CachyOS box; no Deck)

- `make -C src/port test check-front` on macOS and Linux; `python3 -m pytest tools/install tools/steamdeck` (the VDF writer against a hand-built shortcuts.vdf: parse, round trip, entry bytes, numbering, refusal of
  unreadable files, Steam running, backup, `--remove`; the installer's progress against a real install log; `install-gui.sh`'s whole sequence of dialogs with stand-ins for kdialog, qdbus and steam; the layout
  and the `.desktop` files); the Windows job does not run them (they need `sh`) and the C tests are built there like the others.
- **A real X server at 1280x800** (Xvfb with a small window manager of the needed EWMH, plus XTest for a real pointer and keyboard): `SteamDeck=1`, `GAMESCOPE_WAYLAND_DISPLAY` or `PORT_STEAMDECK=1` start full screen,
  the picture is 1024x768 at 1x centred (bars 128 and 16 px, a screenshot), a real pointer click at the drawn "Start New Game" reaches the game at 528,493 (the same at 1920x1080 with the 1.406x picture), nothing
  changes without those, `PORT_FULLSCREEN=0` wins on a Deck. Real X key events typed "Ab 1Z" into the name box once each, with text input managed (on at the name box, off after: `PORT_TEXT_LOG`) and not.
- **The whole install, the way a Deck would do it**: the Steam Deck archive unpacked on runbox, a PATH with no `cc`, `gcc`, `clang` or `make`, the window installer with a stand-in kdialog (and qdbus) and the real disc
  image: the compiler was downloaded (Zig 0.16), 3 min 26 s to a game that starts (the title screen, "Start New Game" with a real click, in the full-screen setup above), `--clean` left 920 MB. The real Konsole
  branch (no kdialog or zenity) ran in the virtual X server: the window showed the installer's text and closed on Enter.
- The Steam shortcut writer on fake Steam folders, never on a real Steam.

## Not verified (what a Deck must check)

1. **Everything on the hardware**: the 1280x800 screen in Game mode (Gamescope, `SteamDeck=1`): that the window really is full screen at the desktop mode, that the scaling and bars are as above and that the
   touch screen and trackpads land where the pointer is drawn (SDL turns touch into the mouse; the touch path through `SDL_RenderSetLogicalSize` was not exercised at all).
2. **The pad**: that SDL sees the Deck with the Gamepad template as a game controller with these button names, the sticks' drift against the 0.22 dead zone (`controller.md`), that the Steam overlay and Steam+X do
   not leave the pad's cursor or a key stuck, that `SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS` is wanted (or whether it moves the cursor while the overlay is up).
3. **The layout file** `controller_neptune_pentamoor.vdf`: written from memory of the format (`controller_mappings`, `group`s with a `mode`, `inputs` with `activators`/`Full_Press`/`bindings`, a `preset` with
   `group_source_bindings`); no Steam to load it in. Unsure: whether Steam lists a file copied into `controller_base/templates/` (as opposed to the per-user `userdata/<id>/config/controller_configs/`), the names
   of the source groups on the Deck (`joystick`, `right_joystick`, `switch`, `left_trackpad`...), the switch inputs `button_menu`/`button_escape`, `absolute_mouse` as the trackpad's plain mouse mode, the trigger
   groups' `output_trigger`, whether a missing `Timestamp` matters. There is no `controller_generic` file: another pad needs only Steam's own Gamepad template (or none: SDL knows most pads).
4. **The Steam shortcut**: `shortcuts.vdf`'s binary format and the app id (the CRC-32 of the quoted exe and the name, top bit set) were written from memory and checked only against themselves; whether Steam takes
   the entry, shows the tag, and keeps `Exe`/`StartDir` as they are (quotes included); that a Steam restart (Game mode) shows it; that the backup is the only change.
5. **The window installer on the Deck's KDE**: kdialog's look, `--getopenfilename` with that filter string, the progress bar driven by `qdbus` or `dbus-send` (`Set "" value N`, `setLabelText`, `close`: the
   usual kdialog interface, run only against stand-ins), the zenity fallback (a stand-in for zenity only: the real one is not installed on any machine used here), whether a double click on the `.desktop` files starts them (the `Exec` line splits and runs with a file
   path or a `file://` one: tested with a shell; KDE's trust prompt for a launcher it has not seen is unverified), that `steam -shutdown` closes Steam and that it starts again.
6. **Steam's on-screen keyboard**: that Steam + X still types into the game (it did not change), and above all that a `SDL_StartTextInput` from the game brings it up by itself in Game mode (the reason for
   managing text input) and that it does not come up where it must not (the title screen); whether it sends key events, text events or both (both are handled once), where it sits on the screen (the name box is at the
   middle: the keyboard may cover it; `SDL_SetTextInputRect` is not called).
7. **SteamOS's own libraries**: the runtime is built on Ubuntu 22.04 (glibc 2.35) and links `libSDL2-2.0.so.0`. SteamOS's SDL2 is what it ships (an `sdl2-compat` over SDL3 on new Arch, as on runbox, or classic SDL2):
   both start; Steam's `LD_LIBRARY_PATH` for a non-Steam game may pick its own SDL2 from the Steam runtime. Python 3 and `python3 -m pip` on SteamOS: not needed (a release carries pefile and capstone).
8. **Sound, music, movies** on the Deck (PipeWire through SDL's audio; the Indeo clips and the ending movie need `ffmpeg` on the PATH, which SteamOS may not have: they are skipped as on any system without it).
9. **A game played through** on a Deck: battery, speed (the 60 ms frame was never run on the Deck's CPU), the Steam overlay, suspend and resume.
10. **Disk**: the numbers above are one machine's. SteamOS's home is on the SSD (or a card): nothing in the install is slow, but 1.2 GB must be free.
