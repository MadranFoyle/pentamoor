# Roadmap and design goals

What the project is aiming at beyond the current state, so decisions made today do not make it harder later. The strategy that got us here is in [PORT_STRATEGY.md](PORT_STRATEGY.md); the state of the native program is in [PHASE_C.md](PHASE_C.md).

## Display (done)

The game has layouts for 640x480, 800x600 and 1024x768 only (art and code branch on the screen's width: [notes/resolution.md](notes/resolution.md)), so the program runs at 1024x768 and the front end does the rest:
scaling to any window or display with the aspect ratio kept and the mouse mapped, better scaling (integer scaling, a sharper filter), and a fullscreen mode. Larger or wider layouts need the game's own layout code, so they wait for the rewrite below.

Done: [notes/display.md](notes/display.md). A fullscreen toggle (F11, Alt+Enter, both sticks held on a pad), the scaling modes `fit`, `integer` and `stretch` and the filters `nearest`, `linear` and `sharp` (keys and `PORT_SCALE`, `PORT_FILTER`),
the mouse mapped through the picture's own rectangle at any window, display and display-scaling factor (a Retina window gets its full resolution), a resizable window that starts as the largest whole multiple of the screen that fits, and `display.cfg`
in the overlay folder that keeps all of it between runs. The pure rules are in `src/port/display.c` and take the screen size as a parameter, as new code should. Not yet seen on real hardware: a visible window on a Retina Mac (a hidden one was checked), Windows with display scaling, Wayland, a real controller (nothing in [notes/display.md](notes/display.md), "Not checked", has changed since).

## Mobile (a proof of concept)

An iPad build exists ([notes/ios.md](notes/ios.md)): the lifted game compiled into an app you build yourself for your own device, SDL2 for the window, a touch layer (`touch.c`: tap, drag, long press and two-finger tap as the right button). It runs in the Simulator; a real iPad has not run it,
and it is sideload only because the app contains code made from the player's own game files. What would come next, in order of what the proof of concept found: running it on a real iPad (memory limits, the scene life cycle that SDL 2.32 lacks), a proper touch design (trackpad mode,
hover, on-screen buttons for the keys the game needs), a smaller idle cost (the game's own spinning loops).
New code should keep taking the screen size and the input as parameters, as the display and touch code do.

## Long term: replacing the lifted code with clean C

Functions are replaced one at a time, each checked against its lifted twin ([PHASE_C.md](PHASE_C.md)). Layout and drawing come first. **Design the replacements so that bigger and wider screens are easy later.** Concretely:

- Put the game's addresses in the build profile ([PHASE_C.md](PHASE_C.md), "Build profiles"), not in the code of a hook, so that a replaced function or another build is a row of a table; the runtime refuses a build it has no profile for.
- Take the screen size as a parameter. Never write 640, 800 or 1024 (or 480, 600, 768) into new code; ask the display layer for the size.
- Compute positions from the size (anchors, margins, rows that fit the space) instead of looking them up in a table made for three sizes. Keep the original's three layouts as the reference to test against: at those sizes the new code must give the same pixels.
- Keep what a screen shows (the state: cards, zones, the map's tiles) apart from where it is drawn, so a larger view can show more of it. The overworld's view of the map is the natural first place to show more at a bigger size.
- Art that exists in three sizes is a dependency of the layout, not of the logic: load it through one function that can pick, scale or substitute.
- Hit regions (the clickable places) come from the same layout the drawing uses, so they cannot drift apart. The controller's card navigation ([notes/controller.md](notes/controller.md)) needs them too.

These are goals for new code; the lifted code stays as it is.
