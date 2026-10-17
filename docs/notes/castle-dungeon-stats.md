# Overworld, third walk: castle gate, castle and dungeon interiors, Clues screen, Wiz Stats Journal and Done

Session on a new game (640x480 for most, one run at 800x600), `PORT_CONTROL`, headless, monsters poked out, teleporting instead of walking.
No crash, hang or wrong hit-test was found in the game (one SIGSEGV came from the script's own teleport, see the end); nothing in `src/port` was changed at the time. The places below were all reached and left again.

## Where things are in the game's memory

| What | Address | Notes |
|---|---|---|
| Location table | 0x67bdf0, 0x80 entries of 100 bytes | dword 0 type (1 village, 2/3 towers, 4 castle, 5 a castle after its wizard fell, -1 empty), dword 1 tile x, dword 2 tile y, dword 4 (0x67be00) flags. Made fresh every game (random), so read it each time |
| Dungeon table | 0x67f000, 15 entries of 0x30 bytes | dwords: x, y (tile), the location it belongs to, byte 0xc colour/theme, byte 0xd level (bit 7 = fixed), +0x10 **knowledge flags**, +0x14 rules. Entries 0-4 sit on the five castles (x,y copied from the castle), 5-14 are the free dungeons |
| Dungeon knowledge flags | 0x67f010 + 0x30*i | bit 0 = the Clues list shows where it is (thumbnail, direction), bit 1 = its creatures, bit 2 = its rules. A free dungeon (i >= 5) **does nothing when walked onto while the flag is 0** (the map code at 0x4e8000-ish sets `DAT_005659b0` and enters only if flag != 0 and the first reward word at 0x67eff0 + 0x30*i is not -1). Leaving it sets the flags to 6 |
| Party pixel / tile | 0x52eff0,0x52eff4 / 0x641010,0x641014 | tile = pixel >> 5; the party is centred at tile*32+16 |
| "Just left a place" latch | 0x5659b0 | set to 1 on entering/leaving a location; the next entry only triggers when it is 0 again (walking away resets it; `poke 0x5659b0 0` does it from a script) |

`peek ADDR N` prints N dwords to the log, so `Game.peek(0x67bdf0, 25*128)` of `tools/soak/pentamoor_ctl.py` reads the whole location table in one call.

## Recipe: reach a castle, a dungeon, the Clues screen, Wiz Stats

New game as in `overworld.md` (640x480: `click 330 308`, `click 90 100`, `key return`; at 800x600 the colour shields are at about (105,125) and "New Game" at (412,385)). Then:

    # read the table, pick a castle (type 4) and a dungeon (free ones: i >= 5)
    loc = g.peek(0x67bdf0, 25*128)          # entry i: loc[25*i] type, loc[25*i+1], loc[25*i+2] tile x, y
    # keep the map quiet (repeat every 0.3 s from a thread/process: the monster table is re-made over time)
    for i in range(12): g.poke(0x67f2d0 + 0x14*i, 0xffffffff)
    g.poke(0x522444, 5000); g.poke(0x522448, 200)              # gold, food

    # castle: put the party on its tile centre; the gate screen opens at once
    tx, ty = loc[25*i+1], loc[25*i+2]
    g.teleport_party(tx, ty)       # NOT four pokes of the position (see "Teleporting" below): the position and the map told to redraw itself
    g.poke(0x5659b0, 0)
    # "Who dares to challenge the Mighty <colour> Wizard? ... Well... No. / Yes, enter the castle."
    g.click(130, 114)   # No   (640x480; 800x600: the box is at the top left, "No" about (130,126), "Yes" about (170,144))
    g.click(150, 128)   # Yes  -> the castle (a maze, see below)

    # free dungeon: same teleport onto a dungeon's tile (table at 0x67f000) after making it "known"
    g.poke(0x67f010 + 0x30*d, 7)            # d >= 5; without this walking onto it does nothing
    g.poke(0x5659b0, 0)

    # leaving: Escape twice (the first one only removes the rule-card panel shown on entering)
    g.key("Escape"); g.key("Escape")

    # Dungeon & Castle Clues: the dungeon-door button of the map's right-hand column, (32,205) at 640x480, (45,235) at 800x600
    g.click(32, 205)       # list (twelve slots; a name highlights yellow under the mouse), click a name -> its detail page, "Done" -> list
    g.click(545, 42)       # Done on the list (680,52 at 800x600)

    # Wiz Stats: the wizard-portrait button, (32,262) at 640x480, (40,325) at 800x600
    g.click(32, 262)
    g.click(523, 18)       # Journal (660,22 at 800x600); its Done is (545,19) (680,22 at 800x600)
    g.click(595, 18)       # Done on Wiz Stats (745,22 at 800x600)

The party's keys inside a castle or dungeon: the keypad diagonals and the arrows are read as scan codes 0x47/0x49/0x4f/0x51 (Home, PageUp, End, PageDown); `key Home` etc. work from
the control pipe, `key Keypad 7` did not move anything. A mouse click moves one step in the diagonal that the click lies in relative to the party's own sprite (a click on the **Exit** cell, the one where the
party started, sends Escape). A screenshot is a good way to see which way the corridor goes: the maze is isometric, End = down-left, Home = up-left on screen.

## What was seen

**Castle gate** (type 4 location): the "Who dares to challenge the Mighty Green Wizard? ..." panel over the wizard's picture, at 640x480 and at 800x600 (Black wizard). Both lines click correctly. "No" returns to the map and sets the latch.
**Castle interior** (640x480 "Wildwood Steading", 800x600 "Castle Necris"): title plate, the rule card of the wizard's castle ("Titania's Song in effect", "Kormus Bell in effect") in a framed panel over the maze, the isometric maze
drawn by the castle's own sprite set (dungeon3.spr themes), the party and "Exit". Walking by key and by mouse worked at both sizes. Events seen on the way, all drawn and clickable: a quiz ("What special ability does the Will-o'-the-Wisp have?", ten answers,
"Correct" with the card), and "Exploring the Castle... you encounter a Summoner! (Titania's Song starts in play!)" which starts a duel: the duel opens with the coin toss movie, the ante screen, the duel with the castle's rule card shown in the
opponent's territory (and the life totals 16/10 of a castle duel), Concede (right button on the table, `Concede > Yes, I'm sure` as in `overworld.md`) gives the "Summoner won" page with both next draws, and then
"You are unceremoniously booted from the stronghold of the Mighty Green Wizard!", which returns to the map (party life 46 -> 45).
**Free dungeon** ("The Paths of Chronus", 640x480): the same machinery with a blue stone theme; the rule card ("Power Struggle in effect"), Escape to leave (twice), back on the map.
**Dungeon & Castle Clues** (640x480 and 800x600): list with the two columns of six slots, the up and down arrows, "Done"; with flag bit 0 each row has the thumbnail of the place (castle sprite or the dungeon's own) and its name; hovering highlights a row yellow; clicking
opens the detail page (name, "Creatures:", "Dungeon Rules:" and the three reward cards fanned out at the bottom right; "Done" returns to the list). With flags 0 the rows are black boxes and only the name is drawn, which is what the code does too.
**Wiz Stats** (STATWIN.DLL, 640x480 and 800x600): portrait, gold, food, amulets, life, the five castle emblems with "Attempts at each castle" (the black castle showed 1 after the run at 800x600),
World Magics, Dungeon Treasures. **Journal** opens the journal page (a scroll bar on the left, a small map of the explored part of the world, an entry per place: "Entered Castle Necris (Black Castle)"), its **Done** returns to
the Wiz Stats page, and **Done** there returns to the map. At 800x600 the journal map sits at the left, lower than at 640x480; the entry label overlaps the town name under it ("Windlass Forge"). Not checked against the original.

## Not fixed, not understood

- **Card text on the castle/dungeon panels at 640x480 is mushy** and some words run together ("Titania's Songleaves play, this effect continues untilend of turn"; the game's own card data has the spaces, `CARDS.DAT`). The card is drawn small, text dark on the wood texture,
  so it looks like the result of scaling the text down (spaces are one pixel). The same card is clean at 800x600 ("Kormus Bell": "All swamps are 1/1 creatures. (These creatures still count as lands.)") and short texts are clean at 640x480 ("Flying / Regenerate"). Looked into since (`castle-text.md`): the original's text is as compressed (a screenshot of its ante card shows "hassummoning"), but its strokes are solid black; ours were pale
  and are now darker.
- "PowerStruggl in effect" and "TitaniasSong in effect": the panel title is the card's 12-character short name, so that is the game's own string, not a port bug.
- Party sprite not visible on the map while standing on a castle's tile: the castle's sprite (a large one) is drawn over it. After a step off it shows again.
- A screenshot taken right after a teleport can show the previous scrolled map frame for one frame (a mountain where later frames showed water); a second shot was right.
- The 640x480 and 800x600 maze layouts were not walked beyond a few steps; the other event types of a castle (treasure, the "dice" events at `Palette_Subsystem_004a2ef0`, a fight against the wizard himself at the end) were not reached.
- Not tried: 1024x768 (the Dungeon Clues/Wiz Stats/castle screens), clicking the up/down arrows of the Clues list with more than twelve entries, the dungeon treasure pick-up.
## Teleporting by poke: the "dungeon 5 crash" (found and explained)

**Entering the dungeon in slot 5 of the saved game's table crashed the process** (SIGSEGV, exit status -11, nothing on stderr; 640x480 only; slots 6 and 9 and the other sizes were fine; old runtimes too).
The dungeon was never entered. Found with lldb on the runtime (`lldb -b -o run -k "bt 16" -- pentamoor-run -m game_magic.dylib MAGIC.EXE`, the game's own control pipe driven from a script): the fault is in the host's `memmove`, called by the
runtime's C-runtime `memcpy` with a length of 0xffffffd0 (-48) from the game's blit function 0x50dce0 (the row-by-row copy of a surface onto itself, at 0x50dfea), called from 0x4c06df, which is the **world map's scroll**
(called by 0x4be643, the map drawing, from the map loop 0x4e73a0 once per frame, with the party's pixel position as its arguments: 1168, 1104 = the poked tile 36,34).

The scroll keeps the part of the map's picture that stays on screen and draws the rest: it works out how far the picture has to move since the last frame (dx, dy, from the table of the map cells' screen positions at 0x6418d0 and
0x6458d0), and copies "the view's width minus |dx|" pixels per row. Walking moves the picture by a few pixels a frame, so that is always a small positive number. The saved game's party stands at tile (30,30) and the
poke put it on (36,34) in one step: dx = 688, more than the view's width of 640 at 640x480 (800 at 800x600 and 1024 at 1024x768: no problem there, which is why only 640x480 crashed), so the width is 640 - 688 = -48, and the game
hands the C library a length of 0xffffffd0. In the original that is the same: an access violation in MSVCRT's `memcpy` (the code is the game's own, the sign is never looked at), so it is **not a runtime bug**. Established
by reading the code, not on the Win98 VM (a poke into the VM needs its gdb stub, for something the code says plainly).

The game never jumps like that by itself: its own teleports (a random tile, 0x4e820a, and a stored position, 0x4e8372, both in the map's walking function 0x4e7f51) write the position and then call **0x4c05ba**, which marks the map
as not drawn (`[0x641884] = 0`, with `[0x558dc8] = [0x52d774] = -1` and `[0x52d778] = 1`); the scroll then sees "not drawn" (0x4c0773-0x4c0780) and draws the whole map without scrolling. A script that teleports the party must do the same:
`Game.teleport_party(tx, ty)` in `tools/soak/pentamoor_ctl.py` writes the position and those four words in one write to the pipe (a test in `tools/soak/test_ctl.py`), and `screen_nav_play.py` uses it for every castle, village and
dungeon it visits. Slot 5 entered that way at 640x480 (and, as a check, by walking the party there in hops of 100 pixels with the old four pokes): "The Paths of Chronus", "Crusade in effect", the Exit cell, the party on it.

The runtime now says what happened instead of dying with a bare SIGSEGV: `memcpy`, `memmove` and `memset` with a length of 2 GiB or more (a negative length that arrived unsigned, which in a 4 GiB address space can only fault) end with
`port: memcpy of 4294967248 bytes (-48 as a signed number) called from the guest's 0x0050dfea: the game passed a negative size` and exit status 2 (`crt.c`, `crt_length_check`). The same poke without the map's
invalidation at 640x480 shows that line.

Found reading the same code path (the same family: a size that is negative as a signed number), **not seen in any game run**: the guest heap (`guest.c`, `heap_alloc`) rounded a size up to 16 and added it to the heap's top in 32 bits. A size of
0xffffffd0 passed the "does it fit" test by wrapping round the end of the address space and moved the top backwards (every block made after it lay on top of live ones); a size of 0xfffffff5 and up rounded to 0 and became a block of 16 bytes.
`calloc` multiplied its two arguments in 32 bits, and `realloc` with no room copied the old block to guest address 0 and freed it. They all answer "no" (NULL) now, as the C library and `HeapAlloc` do, and leave the heap as it was (checks in `test_module.c`).
