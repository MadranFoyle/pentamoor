#!/bin/sh
# sim.sh COMMAND: run the simulator build of Pentamoor in the iOS Simulator (docs/notes/ios.md). Uses a simulated iPad Pro 13-inch named "Pentamoor iPad Pro" (made on `setup`; the
# simulators you already have are not touched), found by name each time.
#
#   tools/ios/sim.sh setup            make the simulator (iPad Pro 13-inch M5, the newest iOS runtime installed) if it is not there, boot it, open the Simulator window
#   tools/ios/sim.sh install          install dist/ios/simulator/Pentamoor.app
#   tools/ios/sim.sh data [FOLDER]    copy the game (default: sources/installed/Magic, the folder that holds Program/MAGIC.EXE) into the app's Documents/Magic
#   tools/ios/sim.sh launch [ENV=V..] start the app; the variables go to it (PORT_CONTROL=..., PORT_FRAME_LOG=1, PENTAMOOR_PROGRAM=duel, ...). Prints the process id
#   tools/ios/sim.sh stop             end the app
#   tools/ios/sim.sh shot FILE        a screenshot of the whole simulator screen (the game's own `shot` through PORT_CONTROL gives the game's 1024x768 picture)
#   tools/ios/sim.sh container        print the app's data folder (Documents/ holds Magic/, port_overlay/ and pentamoor.log)
#   tools/ios/sim.sh udid             print the simulator's id
#   tools/ios/sim.sh shutdown         shut the simulator down (only this one)
#   tools/ios/sim.sh ctl-start        make a control pipe (a FIFO in the app's tmp folder) and launch with PORT_CONTROL set to it; `ctl LINE` writes a line to it
# Environment: SIM_NO_OPEN=1 (setup: do not open the Simulator window), SIM_NAME (default "Pentamoor iPad Pro"), BUNDLE_ID (default org.pentamoor.app.<login>), IOS_RUNTIME (a runtime id, default: the newest iOS).
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SIM_NAME=${SIM_NAME:-Pentamoor iPad Pro}
LOGIN=$(id -un | tr -c 'A-Za-z0-9\n' '-' | tr 'A-Z' 'a-z')
BUNDLE_ID=${BUNDLE_ID:-org.pentamoor.app.$LOGIN}
APP=${APP:-$ROOT/dist/ios/simulator/Pentamoor.app}

udid() { xcrun simctl list devices available | grep -F "    $SIM_NAME (" | head -1 | sed -E 's/.*\(([0-9A-Fa-f-]{36})\).*/\1/'; }
need_udid() { U=$(udid); [ -n "$U" ] || { echo "sim.sh: no simulator named \"$SIM_NAME\": run  tools/ios/sim.sh setup" >&2; exit 1; }; }
container() { xcrun simctl get_app_container "$U" "$BUNDLE_ID" data; }

CMD=${1:-help}
[ $# -gt 0 ] && shift
case "$CMD" in
  setup)
    U=$(udid)
    if [ -z "$U" ]; then
      RT=${IOS_RUNTIME:-$(xcrun simctl list runtimes available | grep -E '^iOS [0-9.]+ ' | tail -1 | sed -E 's/.* - (com\.apple\.CoreSimulator\.SimRuntime\.[A-Za-z0-9-]+).*/\1/')}
      [ -n "$RT" ] || { echo "sim.sh: no iOS simulator runtime is installed (Xcode > Settings > Components)" >&2; exit 1; }
      U=$(xcrun simctl create "$SIM_NAME" com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13-inch-M5-16GB "$RT")
      echo "made \"$SIM_NAME\" ($U) on $RT"
    fi
    xcrun simctl boot "$U" 2>/dev/null || true
    xcrun simctl bootstatus "$U" -b > /dev/null
    [ -n "$SIM_NO_OPEN" ] || open -a Simulator --args -CurrentDeviceUDID "$U" 2>/dev/null || true
    echo "$U" ;;
  udid) udid ;;
  install) need_udid; xcrun simctl install "$U" "$APP" ;;
  data)
    need_udid
    SRC=${1:-$ROOT/sources/installed/Magic}
    [ -f "$SRC/Program/MAGIC.EXE" ] || { echo "sim.sh: $SRC/Program/MAGIC.EXE is not there" >&2; exit 1; }
    D=$(container)/Documents
    mkdir -p "$D"
    rm -rf "$D/Magic"
    echo "copying $SRC to the app's Documents/Magic (about 280 MB) ..."
    cp -R "$SRC" "$D/Magic"
    echo "done: $D/Magic" ;;
  launch)
    need_udid
    for kv in "$@"; do export "SIMCTL_CHILD_$kv"; done
    xcrun simctl launch --terminate-running-process "$U" "$BUNDLE_ID" ;;
  stop) need_udid; xcrun simctl terminate "$U" "$BUNDLE_ID" ;;
  shot) need_udid; xcrun simctl io "$U" screenshot "$1" ;;
  container) need_udid; container ;;
  shutdown) need_udid; xcrun simctl shutdown "$U" ;;
  ctl-start)
    need_udid
    F=$(container)/tmp/control
    rm -f "$F"
    mkdir -p "$(dirname "$F")"
    mkfifo "$F"
    echo "control pipe: $F"
    SIMCTL_CHILD_PORT_CONTROL="$F" xcrun simctl launch --terminate-running-process "$U" "$BUNDLE_ID" ;;
  ctl)
    need_udid
    echo "$*" > "$(container)/tmp/control" ;;
  *)
    sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
    [ "$CMD" = help ] || exit 2 ;;
esac
