# Overworld, third walk: castle gate, castle and dungeon interiors, Clues screen, Wiz Stats Journal and Done

Session on a new game (640x480 for most, one run at 800x600), `PORT_CONTROL`, headless, monsters poked out, teleporting instead of walking.
No crash, hang or wrong hit-test was found; nothing in `src/port` was changed. The places below were all reached and left again.

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
    g.poke(0x52eff0, tx*32+16); g.poke(0x52eff4, ty*32+16); g.poke(0x641010, tx); g.poke(0x641014, ty)
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
