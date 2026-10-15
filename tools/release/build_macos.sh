#!/bin/sh
# build_macos.sh [arm64|x86_64|universal] [output folder]: the runtime for macOS, with SDL2 linked in statically, so a user needs no brew and no SDL2 file beside it.
# Downloads SDL2's source (the pinned release below, checked against its SHA-256), builds it as a static library for each architecture (the x86-64 one is cross-compiled on an
# Apple Silicon Mac with -arch), builds `make -C src/port runtime` against it, and for `universal` joins the two with lipo and signs the result ad hoc (an arm64 program must be signed;
# the linker signs each one, lipo makes a new file). Output: <folder>/pentamoor-run (default dist/macos). Needs Xcode's command line tools, curl, make; no brew.
# Not run: the game modules. Those are built by the user's own installer; this is only the runtime.
set -e
SDL_VERSION=2.32.10
SDL_SHA256=5f5993c530f084535c65a6879e9b26ad441169b3e25d789d83287040a9ca5165
MIN=${MACOSX_DEPLOYMENT_TARGET:-11.0}
WHAT=${1:-universal}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${2:-$ROOT/dist/macos}
WORK=$ROOT/dist/work-macos
mkdir -p "$OUT" "$WORK"

TARBALL=$WORK/SDL2-$SDL_VERSION.tar.gz
if [ ! -f "$TARBALL" ]; then
  curl -fsSL -o "$TARBALL" "https://github.com/libsdl-org/SDL/releases/download/release-$SDL_VERSION/SDL2-$SDL_VERSION.tar.gz"
fi
echo "$SDL_SHA256  $TARBALL" | shasum -a 256 -c -

build_one() {   # arch
  ARCH=$1
  SRC=$WORK/SDL2-$SDL_VERSION-$ARCH
  PREFIX=$WORK/sdl2-$ARCH
  if [ ! -f "$PREFIX/bin/sdl2-config" ]; then
    rm -rf "$SRC"; mkdir -p "$SRC"
    tar xzf "$TARBALL" -C "$SRC" --strip-components=1
    ( cd "$SRC"
      ./configure --prefix="$PREFIX" --host="$ARCH-apple-darwin" --disable-shared --enable-static \
        CC="cc -arch $ARCH -mmacosx-version-min=$MIN" CFLAGS="-O2" LDFLAGS="-arch $ARCH" > configure.log 2>&1 || { tail -30 configure.log; exit 1; }
      make -j"$(sysctl -n hw.ncpu)" > make.log 2>&1 || { tail -30 make.log; exit 1; }
      make install > install.log 2>&1 )
  fi
  # the runtime, with that SDL2 (sdl2-config of the one just built: its flags, and the frameworks a static SDL2 needs)
  SDLC=$("$PREFIX/bin/sdl2-config" --cflags)
  SDLL=$("$PREFIX/bin/sdl2-config" --static-libs)
  rm -rf "$ROOT/src/port/build_macos_$ARCH"
  make -C "$ROOT/src/port" runtime BUILD="build_macos_$ARCH" CC="cc -arch $ARCH -mmacosx-version-min=$MIN" CFLAGS="-std=gnu99 -O2 -Wall -Wextra -Wshadow -Wno-unused-parameter" \
    SDL_CFLAGS="$SDLC" SDL_LIBS="$SDLL"
  cp "$ROOT/src/port/build_macos_$ARCH/pentamoor-run" "$WORK/pentamoor-run-$ARCH"
  strip -x "$WORK/pentamoor-run-$ARCH"
}

case "$WHAT" in
  arm64|x86_64)
    build_one "$WHAT"
    cp "$WORK/pentamoor-run-$WHAT" "$OUT/pentamoor-run" ;;
  universal)
    build_one arm64
    build_one x86_64
    lipo -create "$WORK/pentamoor-run-arm64" "$WORK/pentamoor-run-x86_64" -output "$OUT/pentamoor-run" ;;
  *) echo "usage: $0 [arm64|x86_64|universal] [output folder]" >&2; exit 2 ;;
esac
codesign --force --sign - "$OUT/pentamoor-run"
file "$OUT/pentamoor-run"
otool -L "$OUT/pentamoor-run" | tail -n +2
