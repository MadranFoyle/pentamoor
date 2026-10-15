# Overworld, second walk (village, Buy Cards, castle)

Short session, 640x480, new game, monsters poked out (every ~170 ms; encounters still came in through the poke gaps and were paid).

- **Village food button**: one `click` on "Buy 10 food for 15 gold" now costs 45 gold and gives +30 food, i.e. 3 purchases (was 27). Measured twice
  (gold 4860/44 -> 4815/74 -> 4770/104). Not yet exactly one: a press is HOLD_MS 70 ms (`front.c`) and the UI pass is paced 60 ms (`pace.c`), so a press
  sees the immediate pass plus one or two paced ones. Exactly one needs the press to end after the first pass of 0x41f3ea that sees the button down,
  rather than after a fixed time.
- **Buy Cards** (village button): the "Cards for Sale" screen draws correctly (four cards with prices, "Done" button), no crash or hang. Not clicked
  through (no purchase tried, Done not clicked).
- **Castle**: walking onto the purple building showed the wise man's quest dialog ("Take this message North ... Accept the Quest / Never mind"); it
  draws correctly. Clicking "Never mind" returned to a village screen ("Hornwall Village": Buy Cards, Edit deck/Sell cards, Begin a Quest, Buy 10 food,
  Leave the village), so the building walked into was a village, not a castle. No castle interior or dungeon was reached.
- **Wiz Stats Journal/Done**: not reached in the time.
- No crashes or hangs seen; the process stayed alive for the whole session.
