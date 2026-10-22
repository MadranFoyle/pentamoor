# Is Spells of the Ancients 2.15 the same adventure with a bigger card pool? What it changes in Shandalar, against 1.0

*(Research note, 2026-10-21. It changes nothing in the runtime, the installer or the lifter. The numbers come from the real discs, the real patch and a 2.15 install made with the project's own installer, compared with the 1.0 install by `tools/research/advdiff.py`, `sotacmp.py` and by playing both games headless. No game file, card text, screenshot or generated C is in the repository: names and counts only. "Certain" means read in the files or seen happen; "inferred" means concluded and not seen. Companion to [sota-comparison.md](sota-comparison.md) (the programs, the patch, the cards) and [sota-licence.md](sota-licence.md).)*

## The answer

**It is the same adventure in everything the files let us measure, except that every opponent's deck was chosen again.** The world and the code that makes it, the towns and their menus, the price rule of the shops, the creature table (the 57 kinds of opponent: colour, abilities, terrain, which deck each has), the twelve World Magics, the quests, the pictures of the world, the castles and the dungeons, and the start-of-game rules are byte for byte or constant for constant the same as in 1.0; the adventure's text is the same sentences (2.15 only moves it into a text file, with Spanish, French, Italian and German beside the English). What changed is the **55 deck files of the opponents** (every creature, wizard and the final boss duel with one of them): same size as before (about 60 cards), but with fewer commons and more uncommons and rares, twice as many Arabian Nights cards, **20 % of their cards cards that 1.0's program does not have at all** (the expansion's), no more colour variants, and the final boss's deck cut from 138 cards to 66. So the creatures look, walk and are met as before, and play differently. The expansion's cards reach the player through those decks, through the card choosers (the trade route, rewards, dungeon and castle treasure; these ask the licence-gated pool) and, in three cases, the shops: **the shops' own rule is 1.0's**.

Everything else found is small: the adventure's event log (the Journal) keeps 2000 entries instead of 256, the game warns when the collection nears its 500-card limit (the readme: it fixed a crash), a duel deck may hold 100 different cards instead of 80, a dozen pictures of the adventure's screens were redrawn, and portraits are chosen in a second program (FaceMaker).

## How this was done

1. **Files.** The 2.15 folder is the one `pentamoor-install` makes: the 1.0 install, the cabinet of the expansion's disc over it, the six patch files over that (1,294 files against 1,066). Compared by SHA-256 and name.
2. **Opponent decks.** Read as text (`decks/NNNN.dck`), tied to the creature table, compared by card id with the master card table of each program (`advdiff.py decks`, `creatures`).
3. **Strings.** The adventure's text file of 2.15 (`AdvStrings.txt`, `ADVblocks.txt`) against the strings of MAGIC.EXE 1.0, sentence by sentence by fragments.
4. **Code and tables.** `sotacmp.py` pairs the functions of MAGIC.EXE 1.0 with shandalar.exe 2.15 (1,565 of 1,956 found); 117 of those use the adventure's own variables (location, dungeon, creature, gold, amulet, World Magic and shop tables). `advdiff.py fn` lists, for a pair, only the places where an *immediate number* differs, with stack slots, data addresses and table strides left out (1.0 is a debug build, so every recompile moves registers and strides; 47 of the 117 have no differing number at all, 19 one to three, 51 more: all but a handful of those are text calls, table strides and screen layout). The initialised data of both programs was diffed by 32-bit words, and the creature table and the World Magic table compared byte for byte.
5. **Play.** Both games headless on the same flow (Apprentice, red, 640x480), one control pipe each: screens by eye (not kept), memory read with `peek` at the addresses `sotacmp.py`'s data votes give for 2.15. A scratch change of the runtime's `rand`, `srand` and `clock` (`tools/research/adventure-seed-experiment.patch`, never part of the build) was used to try to force the generator's seed.

## What is different, in one table

| What | 1.0 | 2.15 | Certain / inferred |
|---|---|---|---|
| The 55 Shandalar opponent decks (`decks/NNNN.dck`) | 55 files, 3,302 cards in the base lists (57 to 138 a deck, mean 60.0) | all 55 rewritten: 3,331 cards (56 to 68, mean 60.6) | certain |
| ... commons / uncommons / rares in them | 60.2 / 19.1 / 19.1 % | 53.6 / 22.4 / 22.8 % (rarity column of `INFO.CSV`) | certain |
| ... cards from the Arabian Nights set | 4.6 % | 9.9 % | certain |
| ... cards the 1.0 program has no code for | 0 | 680 entries (20.4 %), in 54 of the 55 decks | certain |
| ... colour variants (`.vBlack` ... blocks of 0 to 5 cards the loader adds for a colour) | in 45 files | in none | certain that the files have them; which colour the game passes was not established |
| ... the final boss (`0999.dck`) | 138 cards, 70 distinct non-basic | 66 cards, 28 distinct | certain |
| ... what is kept | | 55 % of a deck's non-basic cards are still in its 2.15 deck (on average); titles "4th Edition" become "Type 1" | certain |
| Which deck belongs to which opponent | creature table, deck number in each of 57 records | the same 57 records, same numbers | certain (bytes equal) |
| Card pool of the program | 463 table records, 419 cards | 622 records, 563 cards | certain |
| Cards a village or town shop may sell | 375 | 378 (adds Sewers of Estark, Giant Badger, Rukh) | inferred (the stock function's own tests applied to the table) |
| Shop price rule, menus; 4 cards in a village | as played | same: mean price 42.1 and 42.2 gold over 160 village slots each, same 27.5 % basic lands | certain (constants), played (towns: 5 or 6 cards by the code, in both; the town samples taken were invalid and are not used) |
| Starting values (Apprentice): 250 gold, 50 food, the ankh counter 10, 36 cards (13 basic lands and 23), 4 amulets | as played | same | played, both; the start function's constants are equal |
| World generator (128 places: villages, towers, castles, mana domes; roads) | `0x44da25`, `0x44e17e`, `0x44e2e7` | `0x53785a`, `0x537fb3`, `0x53811c`: same code, instruction order only | certain for the code; outputs not compared (see below) |
| Terrain, tiles, village, city, castle and dungeon pictures; 309 sprites | | identical files | certain |
| Creature table: 57 records (colours, ability bits, terrain, deck) | | first 28 bytes of every record identical (2.15 adds a one-byte field and keeps names inline) | certain |
| World Magics: 12 spells, ids and costs | | identical | certain |
| Wandering monsters: how many, how they spawn | | no number in the loop differs; their records grew 20 to 24 bytes | certain for numbers, inferred for behaviour |
| Quests: kinds, wording, mix | | same kinds and sentences; mix 0 / 1 / 2 / "defeat" in 40 villages: see below | played |
| Adventure text | English, in the program | `AdvStrings.txt`, five languages; English sentences unchanged except "Duel this X" for "Duel a X"; wizard and castle names whole strings | certain |
| The adventure's event log (what the Journal lists: places entered, quests, wizards defeated) | 256 entries | 2000 | certain for the number (one `cmp` immediate in `0x40b3c2`), inferred that this is the Journal's log |
| Collection limit | 500 spells, no warning | 500, with a warning near the limit | certain (strings, readme) |
| Distinct cards in a duel deck | 80 | 100 | certain for the duel engine (81 to 101 slots a player), inferred for the adventure |
| Opponent deck table (distinct cards the loader keeps) | 80 | 200 (and a 500 bound) | certain (loop bounds), meaning inferred |
| A new block at the end of the village function (a switch of nine cases that opens the adventure's screens) | | present | certain that it is new; what triggers it was not established (F5 did nothing) |
| Pictures of the adventure screens | | 11 redrawn (`cityinfo`, `cluebutn`, `dun_bar`, `dung_bd`, `infobar`, `mapbttns`, `menu2`, `menu3`, `menu4`, `pedstls`, `tradscrn`), 3 new buttons (`smbuybttn`, `statbut1`, `tradbut1`) | certain that they differ; not decoded |
| Portrait choice | on the new-game screen | FaceMaker, a second program, with new art | certain |

(The rest of 2.15, from [sota-comparison.md](sota-comparison.md): the shell with sealed, gauntlet and single-duel pages, movable duel windows, a dozen rule fixes in the duel engine, the deck editor's filters. None of it is the adventure.)

## The files

The 2.15 install has 1,294 files; all 1,066 of 1.0's are still there: 973 identical, 93 replaced, 228 new.

| folder | identical | replaced | new |
|---|---|---|---|
| Program (top) | 143 | 27 | 24 |
| `SPR`, `SPR800`, `SPR1024` (sprites, three sizes) | 309 | 0 | 0 |
| `Faces`, `Sound`, `Statwin` (videos), `DuelSounds` | 305 | 0 | 22 |
| `CardArt`, `DBArt`, `DuelArt` | 161 | 6 | 4 |
| `Decks` (the opponents') | 0 | **55** | 0 |
| `PlayDeck` (decks of the duel and the deck editor) | 55 | 5 | 31 |
| `Exp1Art`, `FaceArt`, `PlayFace`, `FaceMaker`, `ShellArt` | 0 | 0 | 147 |

The 27 replaced files at the top, by name: `cards.dat` (texts), `deck.exe`, `deckdll.dll`, `magic.exe` (the shell, which replaces `duel.exe`), `magsnd.dll`, `magvid.dll`, `statwin.dll` (the Wiz Stats screen), the readme, `duel.cnt`, `duel.hlp`, `legacy.csv`, `cuecards.txt`, `menus.txt`, `prompts.txt`, two fonts and the eleven pictures named in the table. Unchanged, among others: every picture of the world (`terrain`, `terrain1`, `tiles`, `village`, `city`, `cstline`, `dungeon`, `worlbak1`, `creatures640/800/1024`, `title`) and `DUEL.EXE`, which 2.15 no longer starts. New text files: `AdvStrings.txt`, `ADVblocks.txt`, `advButtons.txt` (the adventure), `UIStrings.txt`, `menusX1.txt`, `promptsX1.txt` (shell and expansion), `STORY.TXT` and `TALE.TXT` (the introduction, German in this copy), `Rogues.csv` (66 named duellists of the shell's single-duel and gauntlet pages, not the adventure), and the card lists the deck editor reads. `PlayDeck` is the folder of the duel and the deck editor: the adventure's own decks are the `Decks` folder (the path variable for `PlayDeck` is set in the same start-up code in both programs; nothing seen in the adventure reads it).

## The opponents' decks

**What a deck file is for.** The adventure builds `decks\NNNN.dck` from a field of the creature table (the code of 1.0, read in the upstream decompilation; the same path strings are in 2.15's program): a creature's `NNNN` is the deck it duels with. The table has 57 records: record 0 is the lair (no deck), 35 are the single-colour creatures (five ladders of seven), 10 two-colour, 4 three-colour, 5 the named bosses of decks 990 to 994, and records 55 and 56 are both the final opponent (deck 999). So the 55 files are all the decks and each has one use. Five (`0016`, `0283`, `0150`, `0076`, `0102`) also make the title screen's demonstration duel, and `0179` is the fallback when a number has no file. The table's numbers are equal in 2.15, so the same files are used.

**What a file holds.** A title line, then `.ID  COUNT  NAME` lines: the deck is a table of up to 80 entries in 1.0 that the opponent draws from at random (a card is taken out of the weights as it is drawn). In 45 of 1.0's files six more blocks follow, `.vNone`, `.vBlack`, `.vBlue`, `.vGreen`, `.vRed`, `.vWhite`, of 0 to 5 cards each (740 cards in all); the loader adds a block's cards only when the caller gives it a matching colour mask (most callers give none). 2.15's files have no such blocks.

**What changed.** All 55 files, none added or removed, no name moved:

| | 1.0 (base lists) | 2.15 |
|---|---|---|
| cards in all | 3,302 | 3,331 |
| cards a deck, mean (min-max) | 60.0 (57-138) | 60.6 (56-68) |
| decks of exactly 60 | 6 (29 are exactly 57, which the colour variant, 0 to 5 cards, makes up to about 60) | 39 |
| commons / uncommons / rares / special | 60.2 / 19.1 / 19.1 / 1.5 % | 53.6 / 22.4 / 22.8 / 1.3 % |
| lands, artifacts, creatures (summon) | 38.2 / 10.3 / 25.1 % | 36.9 / 10.5 / 26.1 % |
| cards of the sets Arabian Nights / Legends / Antiquities / The Dark | 4.6 / 7.8 / 5.4 / 3.5 % | 9.9 / 4.9 / 5.4 / 2.1 % |
| entries that are one of the ten power cards (Black Lotus, the five Moxen, Sol Ring, Time Walk, Timetwister, Ancestral Recall) | 47 | 52 |
| cards the 1.0 program has no code for | 0 | 680 (20.4 %), in 54 decks |
| titles | "(Bl, 4th Edition)", "(R/G, 4th)" | "(Bl, Type 1)", "(Re/Gr, Type 1)"; the Crag Hydra's deck is titled "Great Hydra" |

So they are not "stronger" by power cards (1.0's decks held the same ones); they are the same length, **slightly richer (fewer commons), more Arabian Nights, with the expansion's cards, and without colour variants**. Whether that makes a duel harder was not measured (no duel was played to its end here). Per creature (names are the creature table's, in order; counts only):

| creature | cards 1.0 (base) | colour variants in 1.0 | cards 2.15 | distinct non-basic 1.0 | 2.15 | in both | 2.15 cards the 1.0 program lacks |
|---|---|---|---|---|---|---|---|
| Witch | 59 | yes | 60 | 12 | 12 | 8 | 6 |
| Undead Knight | 57 | yes | 60 | 14 | 14 | 11 | 4 |
| Warlock | 57 | yes | 64 | 9 | 10 | 8 | 0 |
| VampireLord | 57 | yes | 62 | 10 | 12 | 8 | 6 |
| Nether Fiend | 58 | yes | 60 | 12 | 14 | 9 | 4 |
| Necromancer | 57 | yes | 60 | 14 | 11 | 10 | 2 |
| Greater Lich | 61 | - | 62 | 16 | 14 | 8 | 17 |
| Cleric | 57 | yes | 60 | 12 | 12 | 9 | 6 |
| Priestess | 60 | yes | 60 | 14 | 10 | 6 | 9 |
| Crusader | 59 | yes | 60 | 12 | 12 | 7 | 16 |
| Paladin | 57 | yes | 60 | 13 | 13 | 7 | 16 |
| Arch Angel | 57 | yes | 60 | 10 | 13 | 5 | 10 |
| High Priest | 61 | - | 60 | 13 | 11 | 8 | 6 |
| Sainted One | 57 | yes | 60 | 16 | 16 | 8 | 9 |
| Seer | 60 | - | 62 | 12 | 12 | 8 | 6 |
| Merfolk Shaman | 60 | - | 60 | 11 | 12 | 7 | 12 |
| Conjurer | 57 | yes | 60 | 13 | 11 | 9 | 4 |
| Sea Dragon | 57 | yes | 60 | 11 | 10 | 7 | 12 |
| Shapeshifter | 62 | - | 60 | 14 | 13 | 2 | 18 |
| Thought Invoker | 57 | yes | 60 | 12 | 10 | 4 | 7 |
| Astral Visionary | 59 | yes | 58 | 14 | 15 | 12 | 8 |
| Druid | 59 | yes | 60 | 15 | 10 | 6 | 12 |
| Elvish Magi | 57 | yes | 56 | 10 | 10 | 7 | 3 |
| Enchantress | 59 | yes | 66 | 14 | 20 | 11 | 4 |
| Forest Dragon | 58 | yes | 60 | 11 | 12 | 10 | 6 |
| Beastmaster | 57 | yes | 60 | 12 | 10 | 6 | 12 |
| Summoner | 57 | yes | 62 | 11 | 12 | 7 | 6 |
| Great Druid | 57 | yes | 60 | 12 | 15 | 7 | 11 |
| Sorceress | 57 | yes | 59 | 11 | 13 | 10 | 8 |
| Sorcerer | 57 | yes | 60 | 10 | 11 | 8 | 8 |
| Troll Shaman | 57 | yes | 60 | 13 | 11 | 6 | 12 |
| Goblin Lord | 57 | yes | 60 | 10 | 12 | 8 | 4 |
| Hydra | 57 | yes | 60 | 11 | 10 | 6 | 8 |
| War Mage | 57 | yes | 60 | 10 | 11 | 6 | 8 |
| Dragon Lord | 64 | - | 58 | 16 | 12 | 5 | 12 |
| Tusk Guardian | 60 | - | 60 | 13 | 13 | 3 | 26 |
| Sedge Beast | 57 | yes | 60 | 11 | 11 | 4 | 14 |
| Ape Lord | 60 | - | 60 | 13 | 13 | 5 | 16 |
| Centaur Shaman | 57 | yes | 60 | 12 | 11 | 7 | 8 |
| Winged Stallion | 61 | yes | 60 | 14 | 14 | 8 | 9 |
| Fungus Master | 57 | yes | 60 | 12 | 12 | 4 | 14 |
| Centaur Warchief | 57 | yes | 60 | 14 | 13 | 5 | 13 |
| Mind Stealer | 59 | yes | 60 | 15 | 13 | 7 | 16 |
| Lord of Fate | 57 | yes | 64 | 12 | 15 | 12 | 7 |
| Elementalist | 57 | yes | 68 | 16 | 17 | 10 | 4 |
| Aga Galneer | 61 | yes | 60 | 19 | 19 | 4 | 24 |
| Alt-A-Kesh | 62 | yes | 60 | 21 | 14 | 2 | 32 |
| Queltosh | 57 | yes | 60 | 33 | 16 | 2 | 32 |
| Saltrem Tor | 60 | - | 60 | 16 | 14 | 1 | 34 |
| Mandurang | 57 | yes | 60 | 15 | 18 | 11 | 20 |
| Whim | 62 | yes | 61 | 21 | 16 | 9 | 26 |
| Prismat | 62 | yes | 60 | 18 | 24 | 5 | 21 |
| Dracur | 59 | yes | 62 | 21 | 21 | 10 | 24 |
| Kiska-Ra | 66 | - | 61 | 25 | 28 | 24 | 16 |
| Arzakon | 138 | yes | 66 | 70 | 28 | 9 | 32 |

## What was not changed: world, tables, rules

**World generation.** The function that places the 128 locations and the two that draw the roads between them are, in 2.15, the same code to the last constant (`advdiff.py fn 0x44da25 0x44e17e 0x44e2e7`: no number differs; the order of instructions and the registers do). Played worlds had the same make-up: 128 places, 5 castles, 7 to 9 of one kind of tower and 24 to 30 of the other, 86 to 91 villages (two worlds each: 1.0 had 91/24/8/5 and 86/30/7/5 villages, kind-2 towers, kind-3 towers and castles, 2.15 had 88/27/8/5 and 90/24/9/5). **Could one seed give one world in both builds? Tried, not got.** 1.0's generator starts at slot `clock() & 0x7f` of the 128 and then steps by `5n+1`, so with the scratch patch's forced `srand`, `clock` and a forced reset of the generator's state on entry two 1.0 runs repeat each other exactly, and so do two 2.15 runs; 1.0's and 2.15's did not match (7 of 128 positions in common). The generator is entered more than once (the caller retries a world that does not pass its checks: six entries in the 1.0 runs, four in 2.15's) and what an attempt leaves in the map picture it marks is probably part of the next one's input; no cause for the different counts was found. The statement that the generator is unchanged therefore rests on the code, not on the outputs.

**The creature table** (the 57 opponents' colours, ability bits, terrain, deck): 0x44 bytes a record in 1.0, 0x8c in 2.15; the first 28 bytes of every one of the 57 records are equal (`advdiff.py creatures`). 2.15 adds a one-byte field after the first four bytes (an article) and keeps the English name and plural inline.

**World Magics.** The 12 spells' table (ids and costs, 400 to 750 gold at half the stored value) is equal word for word; the explanations are the same words. The one difference is the first spell's name, "Sleight of hand" in 1.0, with a capital H in 2.15.

**Quests and wise men.** The function that makes a village's stock and quest is `0x507c86` in 1.0 and `0x4a0da9` in 2.15; it differs in 19 places by number, and every one is a bigger master table (`sub 0x29` becomes `sub 0x39`: the last 41 records of 1.0's table, the last 57 of 2.15's, are not for sale), a bigger stack frame, string calls that now take a length, and, at its end, a new block that opens the adventure's screens from a switch of nine cases (what calls it was not established). No quest, price or stock constant changed. Villages gave the same four values of the quest-kind variable (0, 1, 2 and a negative one for a creature to defeat) in both builds; on screen, a letter to another place's keeper was seen in 1.0 and creatures to defeat in 2.15 (no quest dialog of each kind was opened in both).

**Shops.** A village shows four cards (played); a town five or six (the code: kind of place + 3, one more with the World Magic "Haggler's Coin"); a card costs `(kind of place + 2) x value` through the clamp (5 to 1000, in steps of 5), doubled or increased by half for a colour that place does not sell. 40 villages each (160 slots) were read from memory in both builds: mean price 42.06 gold in 1.0, 42.19 in 2.15; basic lands 27.5 % of the slots in both; the cards seen in both have the same prices (Deathgrip 90, Pestilence 90, Unstable Mutation 90, Drudge Skeletons 25, a basic land 10 to 15); no card the 1.0 program lacks was for sale in 2.15's 160 slots, and none was in the 36-card starting deck. That fits the program: the stock function admits a card by flags of its master record (`+0x19 & 9`, `+0x1e & 0xc1`, `+0x18 & 0x180`, the same offsets in both tables), and of the 145 records the expansion adds to the table only three pass: 378 admitted cards against 375. The other expansion cards come through the card choosers, which ask the licence-gated pool (set 0 of 409 cards, set 1 of 145: sota-licence.md): the stock function never asks the licence (no registry call was made in two traced stretches of village visits, about 100 seconds). So the readme's "Expansion One cards ... available in towns" is, as far as the code shows, the trade route ("Trade a blue amulet for Any sorceries"), not the stock.

## Played side by side

Both games, Apprentice and red, headless at 640x480 (2.15 also at 1024x768 for the first world), from the title screen: the new-game screens, the map, the Wiz Stats screen, the starting deck, encounters, villages and their shops (40 each), towns, a quest dialog (40 villages each), a castle's gate and its inside, a dungeon, the world map. Screens were looked at and not kept; the numbers were read from memory.

| | 1.0 | 2.15 |
|---|---|---|
| Start | difficulty, colour, portrait, name; 250 gold, 50 food, the ankh counter 10, "36/36" cards, 4 amulets (red: one of its own colour, three drawn at random: the rule is `3 - difficulty` random ones plus one) | the same screens, but the portrait is chosen in FaceMaker, a second window; the same numbers, the same rule |
| Starting deck | 13 basic lands and 23 other cards of the colour (creatures, enchantments, artifacts), drawn at random; the deck editor complains at once about four of one card ("too many ... Remove Extra Cards") | (not looked at) 13 lands and 23 others, drawn at random; none of the 23 was a card the 1.0 program lacks |
| First minutes | the map throws encounters at once: the wizard's toll sentence, then the choices "Duel an Enchantress" and "Pay 70 gold" | the same screen and sentence, the choices "Duel this Sorceress" and "Pay 40 gold"; the card frames are drawn by the new card library |
| Village | Buy Cards, Edit deck/Sell cards, Begin a Quest (or Speak to Wise Man), Buy 10 food for 15 gold, Leave the village | the same five, the same gold |
| Shop | 4 cards, price per card as above | the same |
| Quest | seen: a letter to the keeper of another place (rewarded with a mana link); in 40 villages the quest-kind variable read kind 2 in 16, "defeat" (a negative value) in 13, kind 0 in 4, kind 1 in 3 | "defeat the Sorceress" for a green amulet, "defeat the Mandurang Dragon" for green cards: kind 2 in 15, "defeat" in 6, kind 0 in 8, kind 1 in 7 (the two mixes do not differ significantly: chi-square about 5.5 for 3 degrees, p about 0.14) |
| Castle | the gate asks whether you dare challenge the Blue Wizard (two answers); inside, the castle's name (Mysthold), a panel "Crystal Rod in effect" with the card, the isometric maze, Exit | the same question (Black Wizard), the castle (Castle Necris), "Throne of Bone in effect", the same maze art |
| Dungeon | "The Paths of Chronus", a rule card in effect (Orcish Oriflamme), Exit | the same dungeon, another rule card (Marsh Viper) |
| World map | Plain Map / Info Map / City Info / Done, the place names from the same lists | the same |
| Wiz Stats | portrait, gold, food, life counter, cards, amulets, the 12 World Magic icons, the five castles and "Attempts at each castle", "Dungeon Treasures" | the same layout |
| Deck editor | a button row of colour, kind and set filters, "Exit" | the same layout, "Done" for "Exit" |

Not the same on the screens that were played: the "Duel a X" / "Duel this X" wording, the label "Done" for "Exit", the card frames, the portrait window. F5 pressed in a 2.15 village opened nothing (so the new block at the end of the village function is not an F-key handler), while the map button of the left column opens the world map from a village in both.

**What the play did not show.** No duel was played to its end, so the opponents' new decks were read, not met; no wizard's castle was fought through; a quest was not completed; the trade route and the card choosers (where the expansion's cards would appear for the owner of the discs) were not opened; and the first-minutes shop sample cannot show whether a card of the expansion would turn up in a town (static: three can).

## What was not established

- **Same world from the same seed.** Not reached (see "World generation"): the code is equal, the outputs could not be forced equal, so "the same world" is a statement about the code.
- **How the opponents' new decks play.** Compared as lists (counts, rarity, sets, new cards), not as duels. Whether they are stronger or weaker, and which colour variants 1.0's game actually passed, was not measured.
- **Colour variants.** The loader and the files are certain; which colour mask each caller gives (the player's colours, the creature's) was not traced.
- **Every adventure function.** 117 functions that use the adventure's variables were compared by number; 47 have no differing number and 19 one to three (stride, string and table-size changes); 51 have more and are mostly text calls, screen layout and the larger records (the dungeon and castle functions among them, `0x4856b0`, `0x48f523`, `0x4c24b3`). They were looked at for numbers that are game rules (prices, chances, counts, limits) and none was found beyond the journal, the master-table reserve and the deck limits above; a change in the *order* or *condition* of a branch is not visible to this method.
- **Quests in play.** Completing a quest, the reward chooser, a wizard's attack on a town ("news flash"), the Spell of Dominion's counter and the end of the game were not played; their functions differ only in text calls and strides by number.
- **Difficulties other than Apprentice, and colours other than red.** The start function's constants are equal; only Apprentice-red was played.
- **The first-version question: 1.0 against the 1.1 patch.** The 2.15 readme says version 1.1 faces the player with fewer creatures and adds the right-click menu; the 1.0 disc's program already has the menu (its strings), and the spawn constants of 1.0 and 2.15 are equal, so the disc build is probably the later one, but no copy of the 1.1 patch was available to check (`mtgbv11a.exe` in `sources` is another game's patch).
- **The expansion's cards in the adventure.** Which of the 145 expansion records the card choosers can show was read from the pool function and its bitmaps (409 + 145 cards; set 1 = 143 of the expansion's records and two others), not from a chooser on screen; the earlier note's "not seen in a card picker" still stands.
- **Windows and Linux**, and 2.0 (this note compares 1.0 with 2.15; 2.0's `Decks` folder is 2.15's, since none of the patch's six files is a deck).

## Rerunning

```
# the 2.15 install and its lifted modules as in sota-comparison.md ("Milestone 3"); then, with pefile and capstone:
python3 tools/research/advdiff.py decks     sources/installed/Magic/Program/DECKS sources/installed_sota/Magic/Program/decks sources/installed/Magic/Program/MAGIC.EXE
python3 tools/research/advdiff.py creatures sources/installed/Magic/Program/MAGIC.EXE sources/installed_sota/Magic/Program/shandalar.exe
python3 tools/research/advdiff.py fn        sources/installed/Magic/Program/MAGIC.EXE sources/installed_sota/Magic/Program/shandalar.exe 0x44da25 0x40b3c2 0x507c86 -v
```

The play-through used a scratch copy of `src/port/crt.c` (`tools/research/adventure-seed-experiment.patch`: apply it to a scratch checkout and build with `make -C src/port BUILD=build_seed build_seed/pentamoor-run`; it logs every `srand`, and `RES_SEED`, `RES_CLOCK7` and `RES_HOOKADDR` force the generator's seed) and a control-pipe script of a few dozen lines (`tools/soak/pentamoor_ctl.py`'s `Game`, with the addresses below).

| what | MAGIC.EXE 1.0 | shandalar.exe 2.15 |
|---|---|---|
| gold, food | `0x522444`, `0x522448` | `0x57a7bc`, `0x57a7c0` |
| location table (128 x 100 bytes) | `0x67bdf0` | `0x721e30` |
| dungeon table (15 x 0x30) | `0x67f000` | `0x725040` |
| wandering monsters | `0x67f2d0` (stride 0x14) | `0x725310` (stride 0x18) |
| a village's stock: cards, prices | `0x61e060`, `0x61e0a0` | `0x69eb70`, `0x69ebb0` |
| the quest's kind | `0x61e05c` | `0x69eb6c` |
| party pixel, tile, "just left" latch | `0x52eff0`, `0x641010`, `0x5659b0` | `0x5645b0`, `0x912870`, `0x5975bc` |
