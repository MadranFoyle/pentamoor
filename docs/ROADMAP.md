# Roadmap and design goals

What the project is aiming at beyond the current state, so decisions made today do not make it harder later. The strategy that got us here is in [PORT_STRATEGY.md](PORT_STRATEGY.md); the state of the native program is in [PHASE_C.md](PHASE_C.md).

## Now: display

The game has layouts for 640x480, 800x600 and 1024x768 only (art and code branch on the screen's width: [notes/resolution.md](notes/resolution.md)), so the program runs at 1024x768 and the front end does the rest:
scaling to any window or display with the aspect ratio kept and the mouse mapped, better scaling (integer scaling, a sharper filter), and a fullscreen mode. Larger or wider layouts need the game's own layout code, so they wait for the rewrite below.

## Long term: replacing the lifted code with clean C

Functions are replaced one at a time, each checked against its lifted twin ([PHASE_C.md](PHASE_C.md)). Layout and drawing come first. **Design the replacements so that bigger and wider screens are easy later.** Concretely:

- Take the screen size as a parameter. Never write 640, 800 or 1024 (or 480, 600, 768) into new code; ask the display layer for the size.
- Compute positions from the size (anchors, margins, rows that fit the space) instead of looking them up in a table made for three sizes. Keep the original's three layouts as the reference to test against: at those sizes the new code must give the same pixels.
- Keep what a screen shows (the state: cards, zones, the map's tiles) apart from where it is drawn, so a larger view can show more of it. The overworld's view of the map is the natural first place to show more at a bigger size.
- Art that exists in three sizes is a dependency of the layout, not of the logic: load it through one function that can pick, scale or substitute.
- Hit regions (the clickable places) come from the same layout the drawing uses, so they cannot drift apart. The controller's card navigation ([notes/controller.md](notes/controller.md)) needs them too.

These are goals for new code; the lifted code stays as it is.
