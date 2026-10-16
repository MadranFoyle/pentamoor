# The StatWin clips (68 AVIs)

The installer copies the disc's `StatWin/*.AVI` to `sources/installed/Magic/Program/Statwin`. STATWIN.DLL probes `<drive>:statwin\water.avi` at start-up (a
function at 0x1000353c, the `fopen(C:statwin\water.avi)` in the log) to learn whether the "CD" is there, and builds every clip name from that drive prefix.
Without the files `LoadAVI` answers 5 and the game skips the clip; with them, the code paths below run for the first time in the port.

## What the files are

All 68 are Intel Indeo 4.1 (`IV41`, yuv410p, 15 fps). None is Video 1, so every one needs ffmpeg (a pipe, `movie.c`); the native decoder only does Video 1.
No Indeo-free path: Indeo 4 (wavelet-ish bands, 4x4 slants, motion compensation, its own bitstream) is thousands of lines in ffmpeg, not a small decoder.
`MOVIE_TEST_GAME=1 make -C src/port test` opens every clip on the disc and decodes its first and middle picture (68 of 68 decode, none skipped).

| clips | size | length | sound | role |
|---|---|---|---|---|
| `B_xxx W_xxx U_xxx G_xxx R_xxx M_xxx DG_xxx` (57 files) | 224x168 | 6.7 s | none | the "crystal ball" of a spell on its way to a wizard: starts empty, grows a ball with the creature or wizard in it, on black |
| `Whit-hit Red-hit Blue-hit Grn-hit Blak-hit` | 144..260 x 280..320 | 3.3 to 6.6 s | 8 bit stereo 22.05 kHz | the target wizard, on black, flinching when the spell lands |
| `bubbles fire water vine smoke monster` | 240..368 x 412..460 | 8 to 8.7 s | same | a whole room (the wizard's own, `room-xxx.bmp`) in which the beaten wizard dies; opaque |
| `G_AMGX G_AMGZ G_DJNX ...` (8 files) | 224x168 | 6.7 s | none | not named by any program; chunk ids are `0041` inside `rec ` lists (see below) |

(The names in the first row: the second letter group is the creature type, `AMG` ... `WG`; STATWIN has the table at 0x100115a8 indexed by a byte of the
structure it is handed.)

## When the game plays them (all in STATWIN.DLL, called from MAGIC.EXE's adventure code, not from the duel)

`status_show(struct)` (0x10002209) is the five-wizards window; MAGIC.EXE's 0x4ec98e(mode, wizard) drives it (called from 0x4229d8, 0x4923ee, 0x4ebb2c, ...).
- A wizard is beaten: 0x1000310f(room 0..5) loads `room-xxx.bmp` and plays `bubbles/fire/water/vine/smoke/monster.avi` opaque, then waits for a click
  (`call 0x4ec98e 1 1` from `PORT_CONTROL` reaches it: smoke.avi, 260x460 at 190,10, with its sound).
- A spell is cast at a wizard: 0x1000268a(struct): the ball clip (flag 1, see-through, at the statwin origin + (224, 280)), played to its end; then the
  target's `*-hit.avi` at its own place (table at 0x10011688, +16 bytes each) on top of the wizard's picture; each a see-through video over the window's
  bitmap. (`call 0x3000268a PTR 0` with a struct in guest memory reaches it: dword 0 = 1, byte +0x2d = wizard, byte +0x2e = ball clip.)
- The ending movie `MTGEND.AVI` and the two coin toss movies were already there.

## What was wrong, and the fixes (src/port)

1. **`GetPriorityClass` / `SetPriorityClass` were missing in kernel32.c**: the ball and hit function (0x30002865) raises its process priority while the clips
   play, and the port stopped there ("imports called that are not implemented yet"). Now answered (normal class / ok).
2. **`SetVidPos` and `SetVidTransparency` did nothing**, so a clip appeared centred on the screen (LoadAVI is given a position only for some flags) and as a
   black rectangle. Now `SetVidPos(handle, short[2])` moves the video's window, and `SetVidTransparency(handle, on)` makes every pixel up to 8 in all three
   channels see-through (`movie_key_alpha`, composited in `compose.c`). The real library made the video 8 bit and keyed palette entry 0; the decoder's RGB has
   a little noise on that black, hence the threshold (about half of all pixels of a ball clip are exactly 0, and another tenth lie between 1 and 10; 8 keeps most of the dark part of the pictures). A clip whose figure is dark loses a few shadow pixels to the window behind: not seen to matter.
3. **LoadAVI's flags**: bit 1 means centred (play_video passes 2 for the ending movie); bit 0 and the others only say the video is a child clip. Before, any
   flag meant centred, so a position that was given was ignored.
4. **A loaded video is not visible until `PlayAVI`**: the hit clip's first frame is the wizard, which would otherwise stand there while the ball plays
   (STATWIN loads both clips, then plays them one after the other). `DrawVidBackground(handle)` (the game calls it before and after each clip) hides a
   see-through clip that is not playing; an opaque one (a room) stays as its last picture, which is the room. It also paints the picture that `SetVidBackgroundToDIB(object, handle)` gave
   the slot (the statistics picture: a won duel's screen behind the clips; duel-won-black-screen.md, third report).
5. **ffmpeg is found** on the PATH and, for a program started from a launcher with a short PATH, in /opt/homebrew/bin, /usr/local/bin, /usr/bin; the
   pass-through option is `-fps_mode passthrough` (ffmpeg 5.1 and later) or `-vsync passthrough` before that (probed once). Without it MTGEND repeats frames
   for its 13 empty ones; without ffmpeg at all `LoadAVI` says 4 and the game goes on.
6. **Picture chunks**: stream 0's chunks may be named other than `00dc` (the unused G_AMGX family uses `0041` inside `rec ` lists). Any `00xx` that is not
   `00wb` is a picture now.

## Checked

- Sizes, frame counts and decoding: all 68 (test above); ffmpeg's frame count equals the container's chunk count for each of the 60 clips whose chunks are named
  `00dc`.
- Timing: playback follows the compositor's clock (`index = elapsed * fps`), frames are read in order from the pipe, skipping when late; a 15 fps clip ends
  at 6.7 s. The window's first frame is decoded at LoadAVI (ffmpeg's start-up, about 0.1 s).
- Sound: SMOKE.AVI's 7.8 s of stereo PCM, found in a `PORT_AUDIO_DUMP` of the whole run by correlating the envelope with ffmpeg's decode of the file's
  sound (correlation 0.95 against the rest of the mixer; mean absolute sample difference 10 of 2882 after aligning to the sample, so it is the same samples at
  the same rate and not clipped or stuttering).
- Screens: the crystal ball over the encounter picture (see-through, at (224,280), gone when it ends), the hit wizard, the smoke death animation, the ending
  movie (unchanged), all through `PORT_CONTROL`, and the game carries on after each (death animation: after the click; ending: the encounter screen).
- Missing file: `LoadAVI` 5 (unit test; the game's code then skips the clip, as it did before the installer copied them).
- `test_movie.c`: the key, a transparent window, `SetVidPos`, LoadAVI flags (position, centred, missing), hidden until play, the status while playing,
  DrawVidBackground, unload.

## Not done / not verified

- **(Seen later: duel-won-black-screen.md, third report.) The statistics window itself was not on screen** while these ran (a call into the middle of it, over the encounter screen): STATWIN also paints a foreground
  mask over the video (`wht-mask.bmp` ...: `SetVidForeground` and `DrawVidBackground` with a rectangle) so a clip does not cover the wizard's frame; those
  calls still do nothing, so a clip may overlap the frame by a few pixels. The real trigger (a duel result, or the map's Statistics) was not reached from
  the saved game; the positions are the statwin's own numbers (origin + table).
- Indeo 4 has no native decoder (see above): without ffmpeg the clips do not play.
- The black key's threshold (8) is a guess at what 8 bit palette index 0 did; there is no reference picture.
