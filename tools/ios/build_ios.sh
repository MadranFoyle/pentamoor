#!/bin/sh
# build_ios.sh [simulator|device] [what]: build Pentamoor as an iPadOS app, for the iOS Simulator or for a device (docs/notes/ios.md).
#
#   tools/ios/build_ios.sh simulator           everything below, then the app: dist/ios/simulator/Pentamoor.app (signed ad hoc, for the Simulator)
#   tools/ios/build_ios.sh device              the same for an iPad/iPhone: dist/ios/device/Pentamoor.app, NOT signed (sign it in Xcode: tools/ios/gen_xcodeproj.py makes the project)
#   tools/ios/build_ios.sh simulator libs      only SDL2 and the three game modules (what the Xcode project's first build step runs)
#   ... sdl | modules | runtime | app          one step
#
# What it does, in order:
#   sdl      SDL2 2.32.10 from its pinned source (the SHA-256 below is checked), built as a static library for the SDK with Xcode's own project for it (xcodebuild; no signing, no install).
#   modules  the lifted C of MAGIC, DECK and DUEL (sources/generated/lift_*, made by tools/lift/lift_all.sh from your own game files), compiled for the SDK and joined, per program, into ONE
#            object (ld -r) in which every symbol is local but the program's entry point, renamed pentamoor_game_init_<program>. An app cannot load code from a file, so the three are linked into
#            it; and they share no symbol names after this (docs/notes/ios.md, "Game modules").
#   runtime  `make -C src/port ios-runtime`: the runtime (no game code) for the SDK.
#   app      link the runtime, SDL2 and the modules, make Pentamoor.app (Info.plist, the binary), sign it ad hoc for the Simulator.
#
# Needs a Mac with Xcode (xcrun, xcodebuild, an iOS SDK), curl, make. No Homebrew, no CMake, nothing installed. The output holds code made from your own game files: it is for your own devices
# only, and is never to be committed or given to anyone (dist/ is git-ignored).
#
# Environment: IOS_OUT (default dist/ios), IOS_MIN (minimum iOS, default 15.0), BUNDLE_ID (default org.pentamoor.app.<your login>), JOBS (parallel compiles), PROGRAMS (default "magic deck duel":
# the ones with lifted C present are built), LOG (default: quiet).
set -e

SDL_VERSION=2.32.10
SDL_SHA256=5f5993c530f084535c65a6879e9b26ad441169b3e25d789d83287040a9ca5165
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SELF="$ROOT/tools/ios/build_ios.sh"
MIN=${IOS_MIN:-15.0}
OUT=${IOS_OUT:-$ROOT/dist/ios}
WORK=$ROOT/dist/work-ios
JOBS=${JOBS:-$(sysctl -n hw.ncpu)}
# iOS 27 refuses to start an app linked against the iOS 27 SDK that does not use UIKit's scene life cycle ("UIScene life cycle is required for apps built with this SDK"), and SDL 2.32's
# UIKit code does not. The app is therefore marked as built with an older SDK (the SDK version in its LC_BUILD_VERSION; the code is still compiled and linked against the installed SDK).
# docs/notes/ios.md, "The scene life cycle".
LINK_SDK=${IOS_LINK_SDK:-26.0}
PROGRAMS=${PROGRAMS:-magic deck duel}
LOGIN=$(id -un | tr -c 'A-Za-z0-9\n' '-' | tr 'A-Z' 'a-z')
BUNDLE_ID=${BUNDLE_ID:-org.pentamoor.app.$LOGIN}

# the arguments: a platform, then the step (default all); cc1 is this script calling itself, once per file to compile
PLAT=simulator
case "$1" in
  simulator|device) PLAT=$1; shift ;;
esac
STEP=${1:-all}
case "$PLAT" in
  simulator) SDK=iphonesimulator; TARGET="arm64-apple-ios$MIN-simulator"; PV=ios-simulator ;;
  device)    SDK=iphoneos;        TARGET="arm64-apple-ios$MIN";           PV=ios ;;
esac
SDKPATH=$(xcrun --sdk "$SDK" --show-sdk-path)
CC="xcrun --sdk $SDK clang -target $TARGET -isysroot $SDKPATH"
PLATOUT=$OUT/$PLAT
MODDIR=$WORK/mod-$PLAT
SDLLIB=$WORK/sdl-build/$PLAT/Release-$SDK/libSDL2.a

lift_dir() {    # program -> its lifted C folder
  case "$1" in
    magic) echo "$ROOT/sources/generated/lift_magic_all" ;;
    deck)  echo "$ROOT/sources/generated/lift_deck" ;;
    duel)  echo "$ROOT/sources/generated/lift_duel" ;;
  esac
}
have_programs() {
  for p in $PROGRAMS; do [ -f "$(lift_dir "$p")/handlers_gen.c" ] && echo "$p"; done
}
say() { echo "[ios $PLAT] $*"; }

# ---- the compile of one file of a game module (called through xargs) ----
if [ "$STEP" = cc1 ]; then
  P=$2; SRC=$3; OBJ=$4
  EXTRA=""
  case "$SRC" in */modglue.c) EXTRA="-Dpentamoor_game_init=pentamoor_game_init_$P" ;; esac
  # the module flags of src/port/Makefile (MODFLAGS), for this SDK; -fno-common: no tentative definitions to merge between programs
  $CC -std=gnu99 -O1 -w -fPIC -fvisibility=hidden -fno-common $EXTRA -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT -DLIFT_MODULE -I"$ROOT/src/native" -c -o "$OBJ" "$SRC"
  exit 0
fi

# ---- SDL2 ----
step_sdl() {
  mkdir -p "$WORK"
  TARBALL=$WORK/SDL2-$SDL_VERSION.tar.gz
  if [ ! -f "$TARBALL" ]; then
    say "fetching SDL2 $SDL_VERSION"
    curl -fsSL -o "$TARBALL" "https://github.com/libsdl-org/SDL/releases/download/release-$SDL_VERSION/SDL2-$SDL_VERSION.tar.gz"
  fi
  echo "$SDL_SHA256  $TARBALL" | shasum -a 256 -c - >/dev/null || { echo "build_ios: $TARBALL does not match the pinned SHA-256; deleting it" >&2; rm -f "$TARBALL"; exit 1; }
  if [ ! -f "$WORK/sdl-src/include/SDL.h" ]; then
    rm -rf "$WORK/sdl-src"; mkdir -p "$WORK/sdl-src"
    tar xzf "$TARBALL" -C "$WORK/sdl-src" --strip-components=1
    # SDL's Xcode project also compiles its Metal shaders with the `metal` tool (a separate Xcode component, not always installed); the renderer does not use that result: the shaders are
    # embedded in src/render/metal/SDL_shaders_metal_*.h. So the project is told not to build that one file.
    sed -i '' '/SDL_shaders_metal\.metal in Sources/d' "$WORK/sdl-src/Xcode/SDL/SDL.xcodeproj/project.pbxproj"
  fi
  if [ ! -f "$SDLLIB" ]; then
    say "building SDL2 for the $SDK SDK (a minute)"
    mkdir -p "$WORK/sdl-build"
    xcodebuild -project "$WORK/sdl-src/Xcode/SDL/SDL.xcodeproj" -target "Static Library-iOS" -configuration Release -sdk "$SDK" ARCHS=arm64 ONLY_ACTIVE_ARCH=NO \
      IPHONEOS_DEPLOYMENT_TARGET="$MIN" CODE_SIGNING_ALLOWED=NO SYMROOT="$WORK/sdl-build/$PLAT" OBJROOT="$WORK/sdl-build/$PLAT-obj" > "$WORK/sdl-$PLAT.log" 2>&1 \
      || { tail -30 "$WORK/sdl-$PLAT.log"; exit 1; }
  fi
  [ -f "$SDLLIB" ] || { echo "build_ios: $SDLLIB was not made" >&2; exit 1; }
}

# ---- the game modules ----
step_modules() {
  mkdir -p "$MODDIR" "$PLATOUT"
  PROGS=$(have_programs)
  [ -n "$PROGS" ] || { echo "build_ios: no lifted C found in sources/generated (run tools/lift/lift_all.sh on your own game files first)" >&2; exit 1; }
  JOBLIST=$MODDIR/jobs.txt
  : > "$JOBLIST"
  for p in $PROGS; do
    D=$(lift_dir "$p")
    mkdir -p "$MODDIR/$p"
    FILES=$(ls -S "$D"/*_gen.c; echo "$ROOT/src/port/modglue.c")
    [ -f "$D/modules_gen.c" ] || FILES="$FILES
$ROOT/src/port/modules_none.c"
    for f in $FILES; do
      o="$MODDIR/$p/$(basename "$f" .c).o"
      if [ ! -f "$o" ] || [ "$f" -nt "$o" ] || [ "$ROOT/src/native/lift_rt.h" -nt "$o" ] || [ "$ROOT/src/native/lift_tables.h" -nt "$o" ]; then
        echo "$p $f $o" >> "$JOBLIST"
      fi
    done
  done
  if [ -s "$JOBLIST" ]; then
    say "compiling $(wc -l < "$JOBLIST" | tr -d ' ') files of the game modules ($(echo $PROGS)), $JOBS at a time; the biggest take about a minute"
    # biggest first (the lists above are in size order per program); one line per file: program, source, object
    xargs -P "$JOBS" -L1 sh "$SELF" "$PLAT" cc1 < "$JOBLIST"
  fi
  for p in $PROGS; do
    OBJS=$(ls "$MODDIR/$p"/*.o)
    NEWEST=$(ls -t $OBJS | head -1)
    if [ ! -f "$PLATOUT/game_$p.o" ] || [ "$NEWEST" -nt "$PLATOUT/game_$p.o" ]; then
      say "joining $p into game_$p.o"
      # ld -r: hidden (private extern) symbols become local, so the three programs' objects can share a link; only the renamed entry point stays visible
      $CC -nostdlib -Wl,-r -o "$PLATOUT/game_$p.o" $OBJS
    fi
    BAD=$(xcrun nm -gU "$PLATOUT/game_$p.o" | awk '{print $3}' | grep -v "^_pentamoor_game_init_$p\$" || true)
    if [ -n "$BAD" ]; then
      echo "build_ios: game_$p.o exports more than _pentamoor_game_init_$p (it would collide with another program's):" >&2
      echo "$BAD" | head >&2
      exit 1
    fi
  done
}

# ---- the runtime ----
step_runtime() {
  mkdir -p "$PLATOUT"
  PFLAGS=""
  for p in $(have_programs); do PFLAGS="$PFLAGS -DPORT_STATIC_$(echo "$p" | tr a-z A-Z)"; done
  say "compiling the runtime"
  make -C "$ROOT/src/port" -j"$JOBS" ios-runtime IOS_SDK="$SDK" IOS_MIN="$MIN" IOS_BUILD="$PLATOUT/obj" \
    IOS_SDL_CFLAGS="-I$WORK/sdl-src/include" IOS_PROGRAMS="$PFLAGS" CFLAGS="-std=gnu99 -O2 -g -Wall -Wextra -Wshadow -Wno-unused-parameter" > "$PLATOUT/runtime.log" 2>&1 \
    || { tail -30 "$PLATOUT/runtime.log"; exit 1; }
}

# ---- the app ----
write_plist() {   # file
  cat > "$1" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
$(cat "$ROOT/tools/ios/Info.plist.in" | sed -e "s|@BUNDLE_ID@|$BUNDLE_ID|g" -e "s|@MIN@|$MIN|g" -e "s|@PLATFORM@|$2|g")
</dict>
</plist>
EOF
}

step_app() {
  mkdir -p "$PLATOUT"
  PROGS=$(have_programs)
  [ -f "$SDLLIB" ] || { echo "build_ios: run the sdl step first" >&2; exit 1; }
  for p in $PROGS; do [ -f "$PLATOUT/game_$p.o" ] || { echo "build_ios: run the modules step first (game_$p.o)" >&2; exit 1; }; done
  [ -f "$PLATOUT/obj/main.o" ] || { echo "build_ios: run the runtime step first" >&2; exit 1; }
  APP=$PLATOUT/Pentamoor.app
  rm -rf "$APP"
  mkdir -p "$APP"
  MODOBJS=""
  for p in $PROGS; do MODOBJS="$MODOBJS $PLATOUT/game_$p.o"; done
  say "linking"
  # SDL2's static library needs these system frameworks and libiconv (its README-ios)
  $CC -o "$APP/Pentamoor" "$PLATOUT"/obj/*.o $MODOBJS "$SDLLIB" \
    -framework UIKit -framework Foundation -framework CoreGraphics -framework QuartzCore -framework Metal -framework OpenGLES -framework AudioToolbox -framework AVFoundation \
    -framework CoreAudio -framework CoreMotion -framework CoreHaptics -framework GameController -framework CoreBluetooth -framework ImageIO -framework UniformTypeIdentifiers \
    -liconv -lm -lpthread -Wl,-platform_version,$PV,$MIN,$LINK_SDK
  if [ "$PLAT" = simulator ]; then PN=iPhoneSimulator; else PN=iPhoneOS; fi
  write_plist "$APP/Info.plist" "$PN"
  printf 'APPL????' > "$APP/PkgInfo"
  if [ "$PLAT" = simulator ]; then
    codesign --force --sign - "$APP"
  else
    say "the device build is not signed: open the Xcode project (tools/ios/gen_xcodeproj.py) and pick your team, or sign it yourself (docs/notes/ios.md)"
  fi
  say "built $APP"
  ls -la "$APP/Pentamoor"
}

case "$STEP" in
  sdl)     step_sdl ;;
  modules) step_modules ;;
  runtime) step_sdl; step_runtime ;;
  app)     step_app ;;
  libs)    step_sdl; step_modules ;;
  all)     step_sdl; step_modules; step_runtime; step_app ;;
  *) echo "usage: $0 [simulator|device] [all|libs|sdl|modules|runtime|app]" >&2; exit 2 ;;
esac
