#!/bin/bash
# win_libs.sh OUTFILE: in an MSYS2 MINGW64 shell, write into OUTFILE (one Windows path per line) the DLLs that pentamoor-run.exe needs beside it and that are not Windows' own:
# SDL2.dll and whatever of MSYS2's it loads in turn, and the licence text of SDL2 if the package has one. package.py takes them with --lib and --license.
# Run after `make -C src/port runtime`.
set -e
out=${1:?usage: win_libs.sh OUTFILE}
exe=$(dirname "$0")/../../src/port/build/pentamoor-run.exe
: > "$out"
# what the exe imports, then what those import: only the ones that live in MSYS2's mingw64 folder (Windows' own DLLs are found on every machine)
todo="$exe"
seen=""
while [ -n "$todo" ]; do
  next=""
  for f in $todo; do
    for dll in $(objdump -p "$f" | awk '/DLL Name:/ {print $3}'); do
      p=/mingw64/bin/$dll
      if [ -f "$p" ] && ! echo " $seen " | grep -qi " $dll "; then
        seen="$seen $dll"
        next="$next $p"
        cygpath -w "$p" >> "$out"
      fi
    done
  done
  todo=$next
done
echo "DLLs to ship beside pentamoor-run.exe:"; cat "$out"
lic=$(ls /mingw64/share/licenses/SDL2/* 2>/dev/null | head -1 || true)
[ -n "$lic" ] && cygpath -w "$lic" > "$out.licenses" || : > "$out.licenses"
exit 0
