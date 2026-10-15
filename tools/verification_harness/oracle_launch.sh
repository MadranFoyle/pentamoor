#!/bin/sh
# Boot the Windows 98SE oracle under plain QEMU with a control channel (QMP) and a
# debugger port (gdbstub). Runs from a throwaway qcow2 overlay so the base disk is never
# modified. See docs/ORACLE_VM.md.
#
#   usage: [ORACLE_BASE=base_duel.raw] oracle_launch.sh [overlay-name]     (default: run1)
#   ORACLE_BASE picks the base disk in sources/oracle (default base.raw).
#
# Hardware mirrors the UTM VM (pc-i440fx-10.0, Cirrus, SB16, ne2k_isa, IDE hd on ide.0 and
# an empty CD on ide.1) so Windows 98 sees no new devices and shows no hardware dialogs.
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIR="$ROOT/sources/oracle"
NAME="${1:-run1}"
BASE="${ORACLE_BASE:-base.raw}"
cd "$DIR"
[ -f "$BASE" ] || { echo "missing $DIR/$BASE (see docs/ORACLE_VM.md)" >&2; exit 1; }
rm -f "$NAME.qcow2" qmp.sock
qemu-img create -q -f qcow2 -b "$BASE" -F raw "$NAME.qcow2"
exec qemu-system-i386 \
  -name shandalar-oracle \
  -M pc-i440fx-10.0 -m 512 -rtc base=localtime \
  -vga cirrus \
  -audiodev none,id=snd0 -device sb16,audiodev=snd0 \
  -netdev user,id=net0 -device ne2k_isa,netdev=net0 \
  -drive file="$NAME.qcow2",format=qcow2,if=ide,index=0 \
  -drive if=ide,index=2,media=cdrom \
  -boot c \
  -qmp unix:qmp.sock,server=on,wait=off \
  -gdb tcp:127.0.0.1:1234 \
  -display cocoa
