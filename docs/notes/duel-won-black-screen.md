# "Softlock after the first duel: a black screen" (a won duel)

Report: after winning a duel the two clips played, then the screen stayed black for good; the process kept running, nothing on stderr, no ffmpeg running; a mouse click did clear it
(at 1024x768 and at 640x480; a release build with ffmpeg installed, mouse only).

## Cause

After the "You won!" dialog the duel thread calls STATWIN's clip function (0x3000268a): the crystal ball clip, the wizard's hit clip, then a poll loop (0x3000105a, `PeekMessage(NULL)`
on the duel thread's own queue) that ends on `WM_LBUTTONUP` or `WM_KEYDOWN`. Since PR #107 (of the earlier repository) the clips' windows are *held* when the game calls `DrawVidBackground` (not drawn, still there) so that
input has a window of that thread to arrive at. Keys were routed to the held window (`wm_key_target`), **mouse clicks were not**: they went to the window under the pointer, which is the main
window of the first thread. Only a click inside the hit clip's undrawn rectangle (200x300 at (532,192) at 1024x768, (340,48) at 640x480) or inside the ball clip's reached it. The screen
behind is black (the game itself fills the whole main window with black twice, right after a palette fade, before the clips: `FillRect` (0,0)-(1024,768), brush 0,0,0, from 0x50d5e7), so
there is nothing to aim at, and a person who clicks anywhere and sees nothing happen has a frozen game. A click that lands on one of the two rectangles "clicks past it quickly" to the reward
screen, as the report says.

Reproduced headless, in real time (the clips run their 13 s), with mouse clicks only (a click on the screen's middle every 11 s for a minute: still black, `windows` shows `ShandalarMainClass`
and two `VIDWINCLASS` windows of tid 2, CPU 3-5 %, i.e. an idle wait, not a busy loop); `click 600 300` (inside the hit clip's rectangle) ended it at once. The same through a new game's first
duel ("Duel a Druid" at the first encounter): the win, the held wait, the clue screen.

## Fix (src/port)

- `wm_held_clip()` (user32.c) names the held clip's window; `wm_inject_mouse` (input.c) sends the left button, press and release, to it wherever the pointer is (the release goes where its press
  went). `test_movie` 54 -> 57 checks.
- While a clip is held and the whole screen is black, `compose.c` writes "Click or press a key to continue" at the bottom (the original draws no text; it has the statistics picture there, which
  the third report below gives ours too, so the line now only shows if that picture is missing).
- `ffmpeg` is started with `-nostdin` (a terminal's stdin is otherwise read by it), `PORT_FFMPEG=path|none` chooses it (testing the no-ffmpeg path).

## Checked

- Win: 1024x768 and (headless) the keyboard path as before; the mouse path before the fix (stuck) and after (reward screen, then the clue screen).
- No ffmpeg (`PORT_FFMPEG=none`): `LoadAVI` says 4, the clips are skipped, the win goes straight to the reward screen, nothing hangs.
- The clips' black: `ffmpeg 9.0.2` (Homebrew) decodes RED-HIT.AVI and R_MWZ.avi with a border of exactly (0,0,0) in every frame, so the see-through key (up to 8) matches; the clips are drawn on the black
  the game fills in any case.
- Loss: the "Sorcerer won" dialog (click inside), the lost-card screen, the map, the next ante: no black screen. Concede at 640x480 through the right-click menu ended in the same loss dialog
  (the soak's route).
- The reward screen and the clue screen spin at 100 % CPU while they wait for a click (the game's own loop); not changed.

## Not verified

- A real display (SDL window, renderer): everything here is the dummy video driver. A frame is composed from the window tree at every present, so a missing repaint is not what this was.
- The release layout (modules built by `tools/install/modbuild.py` with the user's compiler), `Esc` out of a duel, a draw, `DUEL.EXE`'s endings (`duel-won.md` has its win), the Gauntlet.
- (Done in the third report below: what the original shows during the clips and the wait.)

# Second report: Urza's Glasses shows black pictures, and the list would not close

The effect's list ("Target Player's Hand", `Pic_Load_004509e8` -> dialog 233, class `ShowListCard`, proc 0x4afc26; the same dialog serves "Opponent library" / "Your Library", which can be
opened in a duel with `call 0x40a16e`, and a short list by poking -1 after the Nth entry of 0x69ef00) showed a grey top half and a black bottom half instead of the picture for some of the cards.

## Cause: a paint of a zero-size window

The art of a card is cached per card at the size of its latest paint (`FUN_0046bcc0`, tables at 0x696a20). The card painter (0x49f8cd) computes the art's size from the window's rectangle; for a
rectangle of 0x0 that is **1x2 pixels**, and a cache hit at any size is used as it is when the list asks with flags 0 (no rescale). The game keeps the opponent's hidden hand as zero-size
`MAGICGAME_CardClass` windows (`(818,306)-(818,306)`), visible and invalid, and the port gave them a WM_PAINT: every card of the opponent's hand was cached as a 1x2 picture (a grey pixel over a black
one, stretched) and stayed that way, so the list showed exactly the opponent's hand black (the trace `PORT_TRACE_FN=0x46bcc0` shows the calls with width 1, height 2). Windows delivers no WM_PAINT for a
window with an empty client area. Fix (user32.c): no WM_PAINT from the pump and none from `UpdateWindow` for a window with an empty client area; it stays invalid and paints when it grows (`test_wm` +2 checks).
Checked: the same list before (Mountain, Lightning Bolt, Manabarbs black, which cards varied with the hand) and after (every picture drawn, no call with width 1).

## Not reproduced: "could not click to close"

By the game's code the list closes on a click on a card, on its empty client area, on its title bar's right end (hit code 200, the "Close" text its own non-client paint draws; our frame is the
standard one and does not show that text), and on Esc; Enter and the right button do nothing. All of these but the unshown text were tried at 1024x768 with a mouse press of 150 ms and with plain
clicks, in a dialog opened by `call 0x40a16e` (a dialog of its own thread, not the duel engine's): the list closed every time. The real Glasses path (the artifact on the table, the effect's prompt) was
not run. If it still happens, `PORT_UI_LOG=1 ./pentamoor 2> pentamoor.log` and the windows list (`PORT_CONTROL`, `windows`) while it is open would say where the click went.

# Third report: "the win screen was black while the animations played before you click"

Not a freeze this time; the question was whether black is what the original shows. It is not: **the original shows the wizards' statistics picture behind the two clips and while it waits for the click.**

## What the original shows (the Windows 98 VM of `docs/ORACLE_VM.md`, 640x480, the retail disc inserted at boot, a duel against a red wizard's Troll Shaman won by writing 0 to 0x6a4a04)

Screenshots through QMP, in time (the guest is slower than real time and uneven, so only the order and the places count, not the timing; the pictures are game content and stay out of the repository):

1. "You won!" (the duel board with a dark blue patterned panel, "You won!", the next draws): **a click closes it; Return does not** (70 s unchanged, tried twice; ours closed on Return too, then: fixed, see `dialogs.md`, "Enter in a dialog with nothing to press").
2. One black screen (the palette fade and the game's two black `FillRect`s, `0x50d5e7`), for about a second.
3. **The statistics picture, full screen at 0,0**: five wizards in a row (blue, green, white, red, black) in front of a dark hall, a large crystal ball on its stand at the bottom middle. It is there from the first picture after the black, before any clip.
4. The crystal-ball clip plays in the ball at (224,280) (a figure grows in it; it ends on a skull), then the wizard's hit clip at (340,48) over the red wizard (a white slash), each see-through over that picture.
5. When the clips are over the picture stays, with the ball empty, with **no text and no window of any other kind**, until a click or a key ends the wait; then the reward screen.

Without the disc in the drive at boot (inserted afterwards through the monitor Windows did not notice it) there are no clips and no picture: the fade, then the reward screen at once (STATWIN looks for `statwin\water.avi` on the CD drives).

## How it was found, and why ours was black

Breakpoints in the original (`probe_hits.py`): `status_show(0x641030, 2)` (STATWIN 0x10002209) calls the ball-and-hit function (0x1000268a) at once, **no STATWIN window is created** (the two `CreateWindowExA` functions never ran), and
`DrawDibDraw` is called, from MAGVID's `DrawVidBackground` (return address MAGVID 0x100034ff), twice at the start (before each clip), at destination (0,0) on one device context (the same one for both calls and for the clips' own frames, which MAGVID draws at the clip's place), with the whole picture.
STATWIN keeps the picture as a DIB object of its own (+0 a vtable, +4 a BITMAPINFOHEADER of 640x480x24, +8 the pixels, read from a BMP when the statistics object is made) and hands it to MAGVID with
`SetVidBackgroundToDIB(object, slot)` right after each `LoadAVI`. **video.c took both calls and did nothing** (`accept`), so nothing ever painted the picture: the main window kept the black the game filled it with, the clips
(see-through, keyed on black) lay on black, and after the last clip the black waited for the click. The earlier note's guess ("the original had the statistics window under the clips") was right about the picture and wrong about
how it got there (no window).

## Fix (src/port/video.c)

`SetVidBackgroundToDIB` remembers the object for the slot (a slot that is not loaded: 2, as for a bad handle) and `DrawVidBackground` paints it on the main window's surface, unstretched, centred when the
screen is larger than 640x480 (the clips already sit at the picture's origin + (224,280) and (340,48) there). The clips composite over it as before; the held clip after the last one still takes the click or key.
`test_movie` 57 -> 63 checks (`test_vid_background`: a 4x2 picture, top row blue, bottom row red, on a main window: centred, whole, nothing around it, the slot check, the held clip still waits).

## Compared with the original

640x480, the same moment (the picture after both clips, waiting): the two screens agree, 8x8 block means differing by 1.2 on a mean level of 30, best alignment at a shift of (0,0), only 3 of 4,800 blocks over 40 and those are the original's mouse
pointer. The original's pixels cannot be matched one for one: it draws the 24 bit picture on a 256 colour display (dithered), ours draws the colours as they are. The first picture after the black, the hit clip's slash and the empty ball are in
both. Not comparable: the timing (the guest is far slower than real time; ours follows the clips' own 15 pictures a second).
800x600 and 1024x768 have no reference (the VM is 640x480): the picture is centred and the clips keep their offsets from it (1024x768: picture at (192,144), clips at (416,424) and (532,192)); this is how MAGVID's
offsets are computed (the DC's size minus the picture's, halved), read from its code, not seen running.

## Checked

Win by the opponent's life poked to 0 and a click on Done at 640x480, 800x600 (no ffmpeg) and 1024x768; Return and a click end the wait (reward screen, then the clue screen as before); `PORT_FFMPEG=none` goes to the reward screen at
once as before (no clip, no picture, nothing waits); headless, SDL dummy drivers.
Not checked: a real window, the other four wizards' pictures (the same DIB for all, one clip each), the Gauntlet's win, `PaintVid`, `LinkVids`, `SetVidForeground`, `SetVidBackgroundToBMP`, `PasteToVidBackground` (still accepted and ignored; STATWIN
did not call them in this flow), a black wizard's win with the disc present (the VM runs without the disc did not play any clip).
