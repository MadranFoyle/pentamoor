# Winning a duel: first attempt (not yet won)

Goal: see the screens after a duel is WON (result dialog, reward / ante card, back to the map). Not reached in this session; what was learned:

- `tools/soak/win_attempt.py` (run from the repo root with `S=<outdir>` set and the dummy SDL drivers) starts a game at 800x600, takes the
  Sorcerer duel, pokes 0x6ff194 to 1 on every tick, pays CASTING prompts by clicking permanents (never cancels them), tries up to 8 hand
  cards per main phase, attacks with all permanents and screenshots every dialog.
- Poking 0x6ff194 changes what `peek` reads, but the on-screen opponent life stayed 10 (screenshot with the poke in place), so that address is
  not the number the engine draws or checks; it is probably a mirror. Poking alone is not a way to a win. The player's address 0x6a3f7c does track
  the on-screen life (it went 10, 8, 7, 4, 1 over a few turns while the opponent's attackers got through).
- The random hand play in the soak policy rarely gets a creature out: with one land per turn it started casts that needed more mana than it had
  and gave up. Attacks did happen ("attack with N permanents" then Done) but with lands only, so no damage.
- Next step: find the real opponent life (diff a memory range before and after the opponent takes a hit), or cast a cheap creature on turn 2-3 on
  purpose (choose the cheapest creature in the hand rows) and attack the turn after.
