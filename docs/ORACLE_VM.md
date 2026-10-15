# Oracle VM: Windows 98SE under QEMU

The reference ("oracle") for verifying the decompilation is the original 1997 game running
unmodified in a Windows 98SE virtual machine. Nothing from the game or from Windows is stored in
this repository: installers, ISOs, disk images and extracted game files live in the git-ignored
`sources/` folder, and you must supply your own legally obtained copies.

## Current setup

- UTM 4.7.5 (QEMU backend) VM named "Windows": mode **Emulate** (software x86, no Rosetta),
  machine `pc` (i440FX, 1996), 512 MB RAM, 4 GiB disk (FAT32), Cirrus VGA, SB16, ne2k_isa.
- Guest: Windows 98 Second Edition. Game installed to `C:\Magic\Program` from the retail
  disc image (`MTG v1.0`).
- The VM bundle lives at
  `~/Library/Containers/com.utmapp.UTM/Data/Documents/Windows.utm` (`config.plist` + `Data/`).

## Preparing the media

- The game disc came as an Alcohol 120% `.mdf/.mds` pair. The `.mdf` is a *raw-sector* image
  (2352 bytes/sector, starts with the CD sync pattern), so renaming to `.iso` does not work.
  Convert with `brew install mdf2iso && mdf2iso "MTG v1.0.mdf" "MTG v1.0.iso"`.
- Getting files out of the VM: shut Windows down, then
  `qemu-img convert -O raw <disk>.qcow2 win98-disk.raw` and
  `hdiutil attach -readonly -nobrowse -imagekey diskimage-class=CRawDiskImage win98-disk.raw`.

## Fingerprints (installed build)

| File | SHA-256 |
|---|---|
| `MAGIC.EXE` | `4dc592695b6ee390485f283feb2a248cd3f3f739749c2800ab3b1100ea03845c` |
| `DUEL.EXE` | `7c4e618b4a8ab4330c71d2dd30637c522573c133d32c667c97924dc8edc2efed` |
| `DECK.EXE` | `193f8abea01d4f2c03b769224b06eece6e263a18f13a5b4e2509ed25a01e3d90` |
| `DECKDLL.DLL` | `a21f714bea465077c4fabe4a407ff7503b0ce5f9bb1a277826e74276e35c2c18` |
| `STATWIN.DLL` | `95bd14de41e8fff84217cdf627a48392da5e7be9c3d064a68e04ed1455334bd7` |
| `MAGSND.DLL` | `6f6d51cd2b8a5800b0b3c994e3ee8217f7b40ba2621f9738783387f3250a9882` |
| `MAGVID.DLL` | `d2db1435ae96e9e41d77ded7a7b222969d44d5af642fa9968fe51768c1ce83a3` |

## Proof this is the decompiled build

Checked by mapping addresses from the decompiled source into the installed `MAGIC.EXE`
(image base `0x00400000`, SizeOfImage `0x32c000`):

- `0x0052f0c0` holds `advfac64.pic` and `0x0052f0d0` holds `dbox.spr`, exactly as the decomp
  references them.
- The functions listed at `0x00474c7f` (143 bytes), `0x00474d0e` (16) and `0x00474d1e` (44)
  each start with `55 8b ec` and end with `c9 c3`, and the sizes tile with no gaps.

Only `MAGIC.EXE` has been checked so far. The other six binaries still need the same test.

## Quirks (all verified the hard way)

- **Two IDE drives maximum.** UTM gives each IDE drive its own bus (`ide.0`, `ide.1`); a third
  fails with `Bus 'ide.2' not found`. The second slot is the CD-ROM.
- **Swapping the CD.** UTM's Drives menu entries are greyed out while running. Shut the guest
  down, quit UTM, edit `Drive.1.ImageName` in `config.plist` with `plutil` (copy the ISO into
  `Data/` first), relaunch, start with `utmctl start Windows`.
- **CD drive must be `ImageType: CD`.** As `Disk` it is a second hard drive and Windows cannot
  see the disc.
- **Input.** The guest mouse does not track synthetic clicks (PS/2 relative mouse); keyboard input
  does reach the guest. Never send Escape then Return blindly: Escape did not dismiss the Shut Down
  dialog, so Return then shut Windows down.
- **ACPI shutdown requests are ignored** (`utmctl stop --request`); shut down from inside the guest.
- **Boot prompt.** Every boot shows a harmless `vnetbios.vxd` missing-file prompt (the network
  driver was never installed). Press a key.
- **Installer boot menu.** The first "Boot from Hard Disk / CD-ROM" menu is the CD's own boot
  loader. Choose CD-ROM until Windows Setup itself has finished.
- **The 1997 patch `mtgbv11a.exe` does not apply.** It patches only `GAME.RFS`, which exists
  neither on the disc nor on the installed disk, and its README is for a different product.

## Scriptable oracle (plain QEMU)

`tools/verification_harness/oracle_launch.sh [name]` boots the same disk with QMP and a gdbstub
(`127.0.0.1:1234`) from a throwaway overlay, using hardware that mirrors the UTM VM
(`pc-i440fx-10.0`, Cirrus, SB16, ne2k_isa, hd on ide.0, CD on ide.1) so Windows shows no
new-hardware dialogs. It expects `sources/oracle/base.raw`: a copy of the raw disk into which a copy
of the `Shandalar.lnk` Start menu shortcut was placed in `WINDOWS\Start Menu\Programs\StartUp`,
so the game launches itself at boot. Delete any `._*` files macOS adds when copying onto the FAT
volume; Windows treats `._Shandalar.lnk` as a broken shortcut.

Gotchas: QMP serves one client at a time; QEMU's gdbstub pauses the guest on attach and
re-triggers a breakpoint at the current PC on continue, so step over your own breakpoint first
(`GDBRemote.resume`); all programs load at `0x00400000`, so verify code bytes before trusting a hit.

## Mouse control

The guest uses a PS/2 relative mouse. Measured on this guest: QMP relative moves in steps of 2
counts move the pointer exactly 1 pixel per count, while larger steps are doubled by pointer
acceleration. `QMP.mouse_goto(x, y)` therefore homes into the top-left corner (clamps at 0,0) and
moves in steps of 2 (paced at 12 ms per step, since the guest drops events that arrive too
fast while the game is busy loading), which is absolute to about a pixel. A click needs about a
0.35 s hold to register. `oracle_ctl.py click X Y` does that and
clicks. The screen is 640x480 and coordinates are guest pixels.

## Booting a different program at startup

The game launches from a shortcut in the guest's Startup folder. To boot `DUEL.EXE` instead, make a
second copy of the base disk (`cp -c base.raw base_duel.raw`), mount it, replace `Shandalar.lnk`
in `WINDOWS\Start Menu\Programs\StartUp` with a copy of `Duel.lnk` (from the "Magic the
Gathering" Start menu folder), delete any `._*` files, and boot with
`ORACLE_BASE=base_duel.raw tools/verification_harness/oracle_launch.sh <name>`.
`probe_duel_start.py ... noclick duel` arms the `DUEL.EXE` breakpoints instead of the `MAGIC.EXE` ones.

## Watchpoints, and things that went wrong

`GDBRemote.set_watchpoint(addr, 4, "write")` stops the guest on a write and reports the address;
`probe_globals.py` uses it. Single-step once to let the write complete, then read the value.

- **Attach watchpoints late.** With three hot globals watched from the duel prompt onward, clicks stopped
  registering; after removing them the click worked, and attaching them once the duel was loading
  worked fine. Cause not proven. Get into the duel first.
- **Close the QMP client properly.** `QMP.close()` must close the buffered reader, not only the
  socket, or QEMU keeps serving the dead connection and the next client waits forever for its greeting.
  Use `with QMP(...)`.
- **A killed VM can hold the debugger port.** If the launcher fails with `Address already in use`, kill
  every `qemu-system-i386` (`pkill -9`) and check `lsof -iTCP:1234`.
- **Duel loads vary.** One duel sat on the same screen for eight minutes with the game idle in its
  message loop; restarting the VM fixed it. A re-homed pointer plus a fresh click also got a stuck
  prompt through once.

## Playing cards through QMP

The duel screen is mouse-driven, and a whole game of it can be played through QMP: land, cast, tap for mana,
end turn, attack, block. What worked, from a duel that reached combat on both sides:

- **The pointer tip lands about 15 to 20 px above and to the left of where you ask.** `mouse_goto(x, y)` positions
  the pointer's hot spot in guest pixels, but the sprite drawn in a screenshot is offset from it, and the
  earlier "clicks that did nothing" were on the wrong row (the row above). Move, take a screenshot, check the
  tip against the target, nudge with `mouse_move(dx, dy)`, then click. Hover first: the row under the pointer
  highlights.
- **Casting.** Click the card in the "Your hand" list (a longer hold, 0.5 s, is safer). The game then shows the
  cost in a bar; click each land you want to tap for mana in the play area (one click each, the cost readout
  shrinks). Casting is complete when the bar disappears.
- **Advancing.** The Done button ends a phase. When clicks are being ignored, the keyboard works: `ret`
  presses Done, and also dismisses the "opponent casts..." cards.
- **Attacking.** Two Done presses reach "Combat phase: choose attackers"; click the creature, then `ret`.
  If the blocker assigns damage, click it to assign.
- **Save states.** `savevm <tag>` through QMP's `human-monitor-command` (0.7 s, about 100 MB in the overlay)
  gives a restore point; `loadvm <tag>` in the same way. Take one right after the duel loads.
- **The duel prompt sometimes freezes** on a new boot (see below); rebooting the throwaway overlay fixed it.
- **A killed probe leaves the guest parked on its last breakpoint** (the screen looks frozen and the pointer
  turns into an hourglass). The probes now stop cleanly on SIGTERM: interrupt, step off any breakpoint of
  their own, remove them, resume. If you kill one hard, reconnect, clear the breakpoints and single-step.
- On the Worldmagic prompt a nudge moved the pointer from "Never mind" onto "Pay the gold" (not clicked);
  check before every click.
