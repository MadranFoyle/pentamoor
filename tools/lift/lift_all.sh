#!/bin/sh
# lift_all.sh: lift every program and library the native port runs, into sources/generated (derived from the game files, never committed).
#   MAGIC.EXE with STATWIN.DLL and DECKDLL.DLL                -> sources/generated/lift_magic_all     make -C src/port
#   DECK.EXE with DECKDLL.DLL                   -> sources/generated/lift_deck          make -C src/port GEN=../../sources/generated/lift_deck BUILD=build_deck
#   DUEL.EXE with DECKDLL.DLL                   -> sources/generated/lift_duel          make -C src/port GEN=../../sources/generated/lift_duel BUILD=build_duel
# Needs the game in sources/installed/Magic and the Python packages pefile and capstone.
set -e
cd "$(dirname "$0")/../.."
PY=${PYTHON:-python3}
GAME=sources/installed/Magic/Program
M=sources/generated/lift_magic_all
$PY tools/lift/gen_handlers.py --program magic --exe $GAME/MAGIC.EXE --out $M --all --no-handlers
$PY tools/lift/gen_dll.py --dll $GAME/STATWIN.DLL --base 0x30000000 --out $M
$PY tools/lift/gen_dll.py --dll $GAME/DECKDLL.DLL --base 0x32000000 --out $M
$PY tools/lift/gen_dll.py --finish --out $M
D=sources/generated/lift_deck
$PY tools/lift/gen_dll.py --main --dll $GAME/DECK.EXE --out $D
$PY tools/lift/gen_dll.py --dll $GAME/DECKDLL.DLL --base 0x32000000 --out $D
$PY tools/lift/gen_dll.py --finish --out $D
U=sources/generated/lift_duel
$PY tools/lift/gen_dll.py --main --dll $GAME/DUEL.EXE --out $U
$PY tools/lift/gen_dll.py --dll $GAME/DECKDLL.DLL --base 0x32000000 --out $U
$PY tools/lift/gen_dll.py --finish --out $U
