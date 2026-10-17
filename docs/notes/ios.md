# iOS and iPadOS (experimental, sideload only)

A proof of concept: Pentamoor as an iPad app, run in the iOS Simulator on an iPad Pro and built so that it can be put on your own iPad from Xcode. There is no JIT and no emulation in it: the lifted game is ordinary C, compiled to arm64
like the rest of the runtime, and the runtime is SDL2.

**Legal, and not to forget.** The app contains code made from the game's own files (the three game modules are the C lifted from *your* `MAGIC.EXE`, `DECK.EXE` and `DUEL.EXE`, compiled in). It is for **your own devices only**: do not give
it to anyone, do not put it on TestFlight or the App Store, do not commit it. Everything it builds goes to `dist/` (git-ignored) and nothing in the repository is made from the game; `tools/release/check_tree.py` still passes. The game's data
(the `Magic` folder) is never inside the app: you copy it into the app's Documents folder yourself.

What was run, and what was not, is listed at the end ([What was tested](#what-was-tested), [Not verified](#not-verified)). Short version: everything below ran in the Simulator on an iPad Pro 13-inch (M5) with the real game files;
**nothing has run on a real iPad**.

## Build and run in the Simulator

Needs a Mac with Xcode (the iPhoneSimulator SDK), `curl`, `make`, and the game installed and lifted as for any build (`tools/install/install.py ... --build`, or `tools/lift/lift_all.sh`: it needs `sources/generated/lift_*` and
`sources/installed/Magic`). Nothing is installed on the Mac: no Homebrew, no CMake, no global tool.

```bash
tools/ios/build_ios.sh simulator          # SDL2, the three game modules, the runtime, the app: dist/ios/simulator/Pentamoor.app  (about 40 s on a 10-core M1 Max, then incremental)
tools/ios/sim.sh setup                    # makes the simulator "Pentamoor iPad Pro" (iPad Pro 13-inch M5, the newest iOS runtime), boots it, opens the Simulator window
tools/ios/sim.sh install
tools/ios/sim.sh data                     # copies sources/installed/Magic into the app's Documents/Magic (280 MB)
tools/ios/sim.sh launch                   # or:  tools/ios/sim.sh ctl-start   (with a control pipe, below)
```

`build_ios.sh` has steps (`sdl`, `modules`, `runtime`, `app`, `libs`; `device` instead of `simulator` for an iPad) and says what each does at the top of the file. `sim.sh` only touches the simulator it made, by name; `sim.sh shutdown` shuts that one down.
The Simulator's device starts in portrait, and the app (landscape only) is then shown letterboxed in it; rotate the simulated iPad (Simulator: Device > Rotate Left or Right) to see it at full size.

**Driving it from the Mac.** `PORT_CONTROL` works as everywhere: `tools/ios/sim.sh ctl-start` makes a FIFO in the app's `tmp/` and launches with `SIMCTL_CHILD_PORT_CONTROL` set to it (any other variable goes the same way:
`SIMCTL_CHILD_PORT_FRAME_LOG=1 tools/ios/sim.sh ctl-start`). `tools/ios/sim_drive.py` wraps the soak tools' `Game` class around that pipe and the app's log (`click 330 308`, `shot out.png` (the game's own 1024x768 picture), `key return`, `windows`, `poke`...),
so `tools/soak` style scripts work against the Simulator. The control steps `tdown ID X Y`, `tmove`, `tup` are fingers (below), so a long press or a two-finger tap can be scripted. For real touches use `xcrun simctl` or the
MCP simulator tool; the app takes what the Simulator sends.

## On a real iPad

You need an Apple developer account (a free one signs for 7 days; a paid one for a year), Xcode, and the iPad in Developer Mode and trusted. Nothing here touches a keychain or a provisioning profile.

1. Install the game and lift it as above (`sources/generated/lift_*` must exist).
2. `python3 tools/ios/gen_xcodeproj.py --team YOURTEAMID --bundle-id com.yourname.pentamoor` (the team is the 10-character id: Xcode > Settings > Accounts, or the Membership page of developer.apple.com; or leave `--team` out and pick the team in Xcode).
   It writes `dist/ios/xcode/Pentamoor.xcodeproj`. The bundle id must be one no other app of your team has. Add `--entitlements` to sign with `tools/ios/Pentamoor.entitlements` (see Memory).
3. Optional, so the first build is quick: `tools/ios/build_ios.sh device libs` (SDL2 and the game modules for the device). The project's first build step does the same.
4. `open dist/ios/xcode/Pentamoor.xcodeproj`, select the Pentamoor scheme and your iPad, check Signing & Capabilities (team, bundle id), and Run (Release is the scheme's default: the lifted code is slow at -O0).
5. Put the game in the app: in Finder (the iPad > Files > Pentamoor > drag the `Magic` folder in) or in the Files app (On My iPad > Pentamoor, copy the folder `Magic` there: the one that holds `Program/MAGIC.EXE`, the same folder as `sources/installed/Magic`).
   It must end up as `Pentamoor/Magic/Program/MAGIC.EXE`. Until it is there the app says so and ends. Then open the app again. Saves and settings go to `Pentamoor/port_overlay/`, and the log is `Pentamoor/pentamoor.log` (Files shows both); the game folder is never written to.
6. A development build runs for as long as the profile lasts (free: 7 days) and has to be signed again after that; the iPad's Settings > General > VPN & Device Management has the "trust this developer" step.

`DECK.EXE` and `DUEL.EXE`: put one word, `deck` or `duel`, in `Pentamoor/program.txt` (default `magic`). In the Simulator `SIMCTL_CHILD_PENTAMOOR_PROGRAM=duel tools/ios/sim.sh launch` does the same.

Debugging a device build from Xcode: the log goes to `pentamoor.log` unless `PENTAMOOR_LOG=console` is in the scheme's environment variables.

## Design

### The game modules are linked in

An app cannot load code that is not signed into it, and nothing can be compiled on an iPad, so there is no `dlopen` of a module. The runtime's two parts become one binary: the three programs' lifted C is compiled for the SDK and linked into the app.

- Each program's files (`handlers_gen.c`, `deckdll_gen.c`, `statwin_gen.c`, `modules_gen.c`, plus `modglue.c`) are compiled with the Makefile's module flags (`-fPIC -fvisibility=hidden`, plus `-fno-common`), `modglue.c` with
  `-Dpentamoor_game_init=pentamoor_game_init_<program>`, and joined with `ld -r` into **one object per program** (`dist/ios/<platform>/game_magic.o`, `game_deck.o`, `game_duel.o`). A relocatable link makes the hidden (private extern)
  symbols local, so what is left to the linker is the one renamed entry point per object: `build_ios.sh` checks with `nm -gU` that nothing else is exported, and fails if it is. That is what keeps the three programs' identical-looking symbol names
  (`LIFT_FUNCTIONS`, `lift_guest`, `LIFT_MODULES`, `LIFTED`...) from colliding in one binary. The three objects are 5.8 (MAGIC), 1.2 (DECK) and 4.5 MB (DUEL); the app binary is 11 MB.
- `gamemod.c` has a static path under `PORT_STATIC_MODULES` (with `PORT_STATIC_MAGIC`, `_DECK`, `_DUEL` for the ones that are there): the "module" is a name (`-m magic`, `game_deck.dylib`, `MAGIC.EXE` all work: `gamemod_static_pick`, tested), and the
  entry point is looked up in a table. The old single-program static build (`PENTAMOOR_STATIC_GAME`) is unchanged.
- Which program runs is a launch setting: `$PENTAMOOR_PROGRAM`, else `Documents/program.txt`, else MAGIC (`iosboot.c`).

### The shell

- **SDL2 2.32.10**, the pinned source of `tools/release/build_macos.sh` (same URL, same SHA-256, checked), built as a static library with SDL's own Xcode project (`xcodebuild -target "Static Library-iOS"`, no signing) for the SDK. One change to its copy of the project: it is told not to
  compile `SDL_shaders_metal.metal` with the `metal` tool (a separate Xcode download that may not be installed; the renderer uses the shaders embedded in `SDL_shaders_metal_*.h`, not that result). SDL's static library carries its own `main()`
  (`SDL_uikit_main.c`), which starts UIKit and calls `SDL_main`; `main.c` has `#define main pentamoor_main` under `PORT_IOS` and `ios_main.c`'s `SDL_main` builds the arguments an app does not have (`-m magic .../Magic/Program/MAGIC.EXE .../Magic`).
- **`Info.plist`** (`tools/ios/Info.plist.in`): landscape left and right only, `UIRequiresFullScreen`, status bar hidden, `UIFileSharingEnabled` and `LSSupportsOpeningDocumentsInPlace` (Documents shows in Files and Finder),
  `UIApplicationSupportsIndirectInputEvents`, `GCSupportsControllerUserInteraction`, an empty `UILaunchScreen` (without a launch screen the system runs the app at a compatibility size), iPad only. iOS draws at the device's own resolution; there is no
  separate high-resolution key to set. There is no app icon yet.
- **Paths.** `$HOME` is the app's data container on a device and in the Simulator, so Documents is `$HOME/Documents`. The game is `Documents/Magic/Program/MAGIC.EXE`, saves and `display.cfg` are `Documents/port_overlay` (`PORT_OVERLAY`, unless the launch names one).
  iOS file systems do not tell names apart by case; `paths.c` copes with both.
- **No other program can be started**: `popen` and `system` are not for an app (`system` is not even in the SDK), so `plat_popen_read` and `plat_system` fail on iOS and `movie.c` never looks for ffmpeg (`PLAT_IOS`). The coin toss movies (the built-in decoder) play; the Indeo clips (the ending, the spell and wizard clips)
  are skipped, as with `PORT_FFMPEG=none`, and the game goes on.
- **Display.** SDL's window is always the whole screen on iOS: the iPad Pro 13-inch gives 1376x1032 points, a 2752x2064 drawable (2.0 per point), and `fit` puts the 1024x768 picture over all of it at 2.69x (the 4:3 shapes match); `sharp` does the
  3x enlarge and smooth reduce. (The picture's mouse mapping uses the window in points and the drawable in pixels, as on a Retina Mac; the touch positions are fractions of the window, so they do not depend on the unit.) The window code that resizes, moves and toggles full screen is not used (F11 and Alt+Enter do nothing here, `display.cfg`'s window
  keys are unused); the iPad is handled as a handheld (`deck = 1` in `front_run`): full screen, text input only for a text field, the pad heard whichever window has the focus.
- **Text.** SDL's text input is on only while a text field has the focus (the Steam Deck's rule), so the on-screen keyboard shows for the name box (seen) and for the game's edit controls, and not otherwise. A hardware keyboard works as on a Mac.
- **Audio.** SDL's CoreAudio device at 22.05 kHz stereo, with the category hint `playback` (sound plays with the silent switch on).
- **Background.** On `SDL_APP_WILLENTERBACKGROUND` the held keys and buttons are let go and nothing is drawn until the app is back (the system ends an app that draws in the background). Not exercised yet.
- **Screen saver.** `SDL_DisableScreenSaver()`: the iPad does not lock while a duel is watched.
- **Controllers, keyboard, trackpad.** Unchanged: SDL's GameController and the keyboard and mouse events of an iPad come through the same code (`pad.c`, `padlog`), `SDL_HINT_MOUSE_TOUCH_EVENTS` is off so that a trackpad is not also a finger.

### Touch

SDL turns a finger into the left button at once, which has no right button and cannot tell a tap from a hold. `touch.c` (pure, no SDL, 72 checks in `make -C src/port test`) does it instead (SDL's conversion is switched off): on iOS always, elsewhere with `PORT_TOUCH=1`.

| Gesture | The game sees |
|---|---|
| a finger down | the pointer moves there (the card under it is shown) |
| a tap (lifted within 500 ms, moved less than 12 picture pixels) | a left click where it was |
| a finger moved more than 12 pixels | the left button goes down where the finger began and follows it, up when it lifts (drags: a card to a deck, a scroll bar, a window) |
| held still 500 ms | one right click there (the card menu); the lift afterwards does nothing |
| a second finger down within 350 ms of the first, and one lifted within 350 ms, neither having moved far | one right click where the first finger was; no left click |
| on the world map: held still 150 ms | the left button goes down and stays down while the finger is held (the party walks toward it), no long press |

The map is told from the rest by the overworld loop's own frame pacing (`pace_map_active`: it has made a frame in the last 0.35 s; it idles between inputs and a finger down wakes it, which the log shows). The time-out values are at the top of `touch.h`. Hover previews,
a trackpad mode, an on-screen help are not here: a proper touch design comes later. With `PORT_PAD_LOG=stderr` (`SIMCTL_CHILD_PORT_PAD_LOG=stderr`) each finger and each button it makes is logged.

### The scene life cycle (the one real problem found)

Xcode 27's SDK makes iOS 27 refuse an app linked against it that does not use UIKit's scene life cycle: "Application failed to launch: UIScene life cycle is required for apps built with this SDK" (seen in the Simulator's log; the app is gone after
a second). SDL2 2.32 has no scene support (`grep UIScene` finds nothing). The workaround, in `build_ios.sh` and in the Xcode project: the app is linked with `-Wl,-platform_version,ios,15.0,26.0`, which puts SDK 26.0 in its `LC_BUILD_VERSION` (the code is still
compiled and linked against the installed SDK; only the number it declares is older). That is accepted: the app ran on the iOS 27.0 Simulator runtime built this way, and the same app does not run linked as 27.0. Costs: it is a declaration that is not true of the build, and
a later iOS may stop honouring it; the proper fix is scene support in SDL's UIKit layer (a scene delegate and windows made with a window scene), which is a patch of SDL or a newer SDL. `IOS_LINK_SDK` changes the number. **It is not known what a real iPad on iOS 26 or 27 does with it.**

### Memory

The guest's 4 GB address space is `mmap`ed `PROT_READ|PROT_WRITE`, `MAP_ANON|MAP_PRIVATE|MAP_NORESERVE` (`plat_posix.c`), untouched pages cost nothing, and the game touches under 200 MB (in the Simulator: resident 34 MB at the title, 65 to 190 MB in encounters, duels and walking over a long session; virtual size about
450 GB for the process, which is the Simulator's own and the Mac's). **In the Simulator the reservation succeeded and the game ran**, which says nothing about a device's limits: a device has a smaller address space than a Mac and a jetsam limit on resident memory.
If the reservation fails on an iPad (the app says `cannot reserve the guest's address space` in `pentamoor.log`), or the system ends the app for memory, turn on the two entitlements in `tools/ios/Pentamoor.entitlements`
(`gen_xcodeproj.py --entitlements`): `com.apple.developer.kernel.extended-virtual-addressing` (more address space) and `com.apple.developer.kernel.increased-memory-limit` (a higher resident limit). They need their capabilities on the app id, which Xcode's automatic signing adds.
The guest's threads are host threads with the default stack (512 KB on iOS, as on a Mac), as before; nothing else needed a change. `backtrace` is only in the coverage build, and the iOS build has none.

### Xcode project

`tools/ios/gen_xcodeproj.py` writes the project itself (the old text format, no generator, deterministic, 13 tests). `GameLibs` is an aggregate target whose script runs `build_ios.sh <platform> libs` in a clean environment; `Pentamoor` compiles the runtime's files
(the list is `make -C src/port print-ios-src`, the Makefile's own, so the two cannot differ) and links them with the objects and SDL2 (`IOS_PLAT` is `simulator` or `device` by SDK). It builds with `xcodebuild -scheme Pentamoor -sdk iphonesimulator` (and `-sdk iphoneos CODE_SIGNING_ALLOWED=NO`);
the Simulator build from it runs.

## What was tested

All on an Apple M1 Max, macOS 27.0.1, Xcode 27.0 (iPhoneSimulator 27.0 SDK), the iPad Pro 13-inch (M5) simulator on the iOS 27.0 runtime, the real game (v1.0 disc install), arm64 only.

- Builds: the Simulator app (about 40 s from nothing: SDL2 with `xcodebuild`, the three modules compiled 10 at a time, the runtime, the link), the device app (links, unsigned), the Xcode project for both SDKs (`xcodebuild`, signing off) and its Simulator app launched.
- All three programs start from the same app binary (MAGIC.EXE played, DUEL.EXE and DECK.EXE to their first screen). The app starts, finds the game in Documents, shows the title screen (`shot` through the control pipe is the game's own picture: the same as on a Mac), the menu is up in about 10 s from the launch. Without the game it shows an alert with where to put it (seen).
- **Real touch** (the MCP simulator tool's taps and holds): Start New Game, the difficulty, colour and visage screens, the on-screen keyboard coming up for the name box, a duel from the coin toss (Play first, Start the duel), playing a land, **a long press on a card opens its right-click menu**
  (View in full card, Show ID tags ...), Done, the won-duel flow ("You won!", the reward screen, taking the cards, the Druid's message), the overworld, a village (Leave the village), **a held finger on the map walks the party** (the map scrolled, stamina went down), Resume Game and the encounter screens of the saved game.
  A **two-finger tap** and the rest of the multi-touch ran through the control pipe's finger steps (the same code path from the SDL finger events on), since the simulator tool has one finger. The win was made by setting the opponent's life to 0 with `poke` (as `tools/soak/won_dialog.py` does), not by playing it out.
- Audio: SDL opened the CoreAudio device with no error and pulled the mixer in real time (`PORT_AUDIO_DUMP`: 22 s of samples in 22 s; real, loud samples from the duel's first sound on). Nobody listened.
- **Speed and CPU** (the Simulator runs the app natively on the Mac's arm64, so these are the Mac's numbers, only indicative of an iPad): the overworld ran at the game's own 60 ms frame (`PORT_FRAME_LOG=1` reports a frame over 75 ms: none while walking, only the long gaps when the loop idles between inputs).
  CPU as `top` saw it: title screen and encounter screens 110 % (one core and a bit) and the Mac's own run of the same screens on SDL's dummy driver is 100 %, because the game's own loops there spin; a duel board 22 %. A spinning loop is a battery question on an iPad, not a speed one; it has not been looked at.
- `make -C src/port test check-front check-module check-run check-program check-build`, `pytest tools/install tools/lift tools/steamdeck tools/release tools/ios` and `tools/release/check_tree.py` pass. `make -C src/port ios-runtime` (the runtime's 48 files compiled for iphonesimulator arm64, no game files) is in the macOS CI job.

## Not verified

- **Anything on a real iPad**: signing, the app starting under the device's limits, the 4 GB reservation, the memory limit, the scene-life-cycle workaround on a real iOS 26 or 27, thermals, battery, frame rate on an A-series or M-series iPad, the keyboard when the iPad is really held landscape.
- The Simulator device was in portrait the whole time and showed the landscape app letterboxed at three quarters of the width; the touch mapping was checked in that state (a tap lands where it is drawn, by the log's picture coordinates), landscape at full size was not looked at.
- Backgrounding and coming back, Stage Manager and window resizing (the app asks for full screen and is not meant to be resized), orientation changes, an Apple Pencil, a trackpad or an external keyboard on the iPad itself, a physical game controller (SDL's gamepad subsystem started and the Simulator's own "Gamepad" was found).
- DECK.EXE and DUEL.EXE as the iOS program were started (`PENTAMOOR_PROGRAM=duel` shows the standalone duel program's setup dialog, `deck` the deck builder with its "New Deck" and the card row) and not played; only MAGIC.EXE was played. The ending movie and the spell clips (no ffmpeg on iOS). Sound by ear. Long sessions (the soak tools can run against the Simulator through `sim_drive.py`; they were not).
- The `build_ios.sh` flow on another machine or another Xcode: SDL's Xcode project and the `metal` tool's absence are version dependent. The CI step compiles only the runtime.

## Known limits

- Touch is basic: no hover, no trackpad mode, no on-screen buttons for Done or Escape (a hardware keyboard or controller has them), and the map's finger-hold needs 150 ms before the party moves.
- No ffmpeg clips; the Indeo movies are skipped.
- The game's own loops spin at 100 % of a core on some screens (the title, the reward and clue screens, encounter screens), as on every platform.
- No app icon, no launch image, English only, iPad only (the 4:3 picture fits an iPad; an iPhone would need a layout).
- The workaround for the scene life cycle (above) may stop working with a later iOS or Xcode.
- The control pipe, the log and the data folder are for development: a signed device build is for your own iPad.
