# The overworld, walked in the native port

(The coordinates in the older notes (this one, `castle-dungeon-stats.md`, `file-dialogs.md`, `gauntlet.md`, `dialogs.md`) are 640x480 unless they say otherwise: since the default became
1024x768, start with `PORT_RES=640x480` to use them as written. See [resolution.md](resolution.md).)

What was done on the map you walk on after a duel, with `PORT_CONTROL`, headless (`SDL_VIDEODRIVER=dummy`). Mostly seen at 640x480; at 800x600 and 1024x768 only the map, the encounter screen
and (800x600) the Wiz Stats screen.

## Reaching the overworld

A new game starts on the map but throws monsters at the party at once: the first thing on screen is an encounter screen ("Those who enter the domain of the
Mighty ... Wizard must pay for the privilege. Will you... Duel a X / Pay N gold"), and a second and third follow when the party has not moved. Three ways out:

1. **Pay.** Click the "Pay N gold" line (640x480: `click 285 336`; 800x600 and 1024x768 move it, take a shot first). The party keeps its gold-5000 poke below.
2. **Concede a duel** (what the encounter chain makes you do when you cannot pay): `click 285 322` (Duel), about 24 s later `click 300 250` (the coin-toss
   movie), `click 473 377` (Start the duel), then `rdown 300 330`/`rup`, `click 340 318`, `click 560 319` ("Yes, I'm sure"), and two `key return`. That is the
   map again, with the encounter's monster gone. Winning goes the same way.
3. **Take the monsters out of the game's memory.** The overworld's monster table is 12 entries of 0x14 bytes at 0x67f2d0 (the type is the first word, -1
   for none; the next three are x, y and a colour). `poke 0x67f2d0 0xffffffff` (and 0x67f2e4, 0x67f2f8, ...) empties it, and `poke 0x522444 5000` is the
   gold (0x522448 is the food, 0x522450 the quest's town). Without the monsters walking is quiet. They are re-made over time, so a script that walks
   for a while repeats the pokes every half second.

Recipe (new game, 640x480; `PORT_CONTROL` is a fifo):

    mkfifo /tmp/ow/ctl; ov=$(mktemp -d); cp -R sources/emu_overlay/. $ov/
    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy PORT_CONTROL=/tmp/ow/ctl PORT_OVERLAY=$ov PORT_STUB=1 \
        src/port/build/pentamoor-run -m src/port/build/game_magic.so sources/installed/Magic/Program/MAGIC.EXE &
    sleep 10; echo "click 330 308" > /tmp/ow/ctl     # New Game
    sleep 4;  echo "click 90 100"  > /tmp/ow/ctl     # a colour
    sleep 4;  echo "key return"    > /tmp/ow/ctl     # the name
    sleep 9                                           # the first encounter screen
    echo "click 285 336" > /tmp/ow/ctl                # pay (repeat for the next encounter)

Walking is a held button: `down X Y`, wait, `up` (X Y is where on the map; the party goes toward it). 6 s of `down 270 300` crossed water and rough ground
(slower, as the notes of the frame loop say); `down 310 100` for 9 s walked into a village. `PORT_FRAME_LOG=1` was quiet.

## What worked

- The map, at all three sizes, with the game's own larger art. Walking, terrain, towns drawn on it, the stamina and food bars.
- Entering a village (`Mardrake Village`: Buy Cards / Edit deck/Sell cards / Begin a Quest / Buy 10 food / Leave the village): the screen draws, the
  wise man's quest dialog opens ("Accept the Quest / Never mind", the Never mind line goes back), Edit deck opens the deck builder (46 cards, the gold
  on top) and its Exit goes back to the village.
- The right-hand column of the map: the spell book, the world map screen (the whole world as a small map with the town names and "Done"), the dungeon
  door button and the wizard portrait (Wiz Stats, below).
- 800x600: the map and Wiz Stats (drawn at 800x600 by the DLL itself, which has its own layout) came out right.
  1024x768: the encounter screen and the map came out right.

## Found, fixed

**The Wiz Stats screen (STATWIN.DLL) was a black rectangle.** Two reasons, both fixed in `src/port`:

- Its window procedure answers `WM_PAINT` with `InvalidateRect` and draws in `WM_ERASEBKGND` (which it handles itself and answers 1, never
  `DefWindowProc`). Windows sends `WM_ERASEBKGND` ahead of the `WM_PAINT` it hands out for a window whose update region is marked for erasing; the port
  sent it only when the procedure called `DefWindowProc(WM_PAINT)` or `BeginPaint`, which this one does not. A new top-level window and a shown one are now
  marked for erasing, and `next_message` (`user32.c`) sends `WM_ERASEBKGND` before it returns the `WM_PAINT` (once, whatever the procedure answers; dialogs keep
  their own path). `test_wm` has 3 more checks (`test_erase_before_paint`: 104 in all).
- The screen is one `DrawDibDraw` of a 640x480 24-bit DIB, and `DrawDibDraw` was a stub that returned 1. It draws through the `SetDIBitsToDevice` code now
  (`video.c`, unstretched: the three places the game calls it use the source's size). With both, the picture of the five wizards, the bars and the
  counts come out; the window is the DLL's, so at 800x600 it is that size too.

## Found, not fixed

- **One click on a town's button repeats.** *Correction (documentation audit, 2026-10): fixed since: a click is one pass of the game's loop, see [click-one-pass.md](click-one-pass.md). What follows is how it was found.*
   In a village, "Buy 10 food for 15 gold" fired 27 times from one `click` (405 gold, +270 food). The town's loop
  (the `while (DAT_006265fc == 0)` at 0x508cd7's caller, `FUN_0041f3ea` in `magic_all.c`) runs the button's handler on every pass while the button is
  down, and each pass is only a redraw, so the number of repeats is the press's length (`HOLD_MS` 70 in `front.c`) over the time of one pass (about 2.6 ms
  here). The original did the same (each pass loaded and drew a village picture, which was slower, so a click gave a few). A fix would end a press when the
  game has pumped its window's messages once after the button-down message was delivered, rather than after 70 ms (the overworld's frame wants exactly that
  too), or pace this loop like `pace.c` paces the map's. Not done: the press's length is shared with the other screens.
- **Card text at 1024x768** (the encounter screen's cards): lines run through the text boxes of the two cards, which they do not at 640x480. Not looked into. *Correction (documentation audit, 2026-10): fixed since, the metrics the game wraps by were not the original's: [card-text-metrics.md](card-text-metrics.md).*
- Not walked here (the later notes did: [castle-dungeon-stats.md](castle-dungeon-stats.md), [journal-done.md](journal-done.md), [resolution.md](resolution.md)): castles, dungeons, the Journal and the Done button of the stats screen, buying cards (the Buy Cards screen was not opened),
  the status screen of a town at 800x600 and 1024x768, and walking with a held mouse at the larger sizes beyond a first step. The scripts cost most of the time
  on the map: each screenshot needs the monsters held off and the party to stay put, and the first encounter chain cannot be skipped without paying or conceding.

## Fixed afterwards: one click repeated

Every screen's loop (the village, the castle, the menus, the shops) calls `0x41f3ea` once a pass with the mouse's place and button, and the button's handler runs on every pass while the
button is down; nothing paced those loops (a pass was 2.6 ms), so a click that lasts 70 to 100 ms bought food 27 times. `pace.c` now has a pre-call hook (`port_prehook`: runs before a
lifted function, which then runs as usual) on `0x41f3ea` that, for a pass with the button down, waits out the frame period (60 ms, `PORT_FRAME_MS`) since the last such pass. A pass with the
button up is not touched, so menus stay quick (an earlier version paced those too and broke the new-game flow: the clicks that choose a difficulty were lost). Measured: a button held for
1.2 s gives passes 60 ms apart (13, where there were hundreds); a short click gives one or two repeats, as on a 1997 machine. Not re-tested in a village (the Buy button itself).

