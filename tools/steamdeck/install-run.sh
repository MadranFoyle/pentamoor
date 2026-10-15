#!/bin/sh
# install-run.sh ISO RCFILE [noprompt] - run the installer in this terminal window with its own progress text, and write its exit status to RCFILE.
# install-gui.sh opens a Konsole (or xterm) window with this when it has no progress bar to use; the window stays until Enter is pressed so that the end of the text can be read.
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd) || exit 1
ROOT=$(CDPATH='' cd -- "$HERE/../.." && pwd) || exit 1
cd "$ROOT" || exit 1
PY=$(command -v python3 || command -v python)
echo "Pentamoor: installing from $1"
echo "(a few minutes: reading the disc, translating the game to C, compiling it; this window shows the installer's own text)"
echo
"$PY" "$ROOT/pentamoor-install" --yes --clean "$1" 2>&1 | tee "$ROOT/pentamoor-install.log"
# the pipeline's status is tee's, so ask the log whether the installer said it was built
if grep -q '^built\.' "$ROOT/pentamoor-install.log"; then RC=0; else RC=1; fi
echo "$RC" > "$2"
echo
if [ "$RC" = 0 ]; then echo "Done. Pentamoor is installed."; else echo "The installation did not finish (see the text above, and pentamoor-install.log)."; fi
if [ "$3" != noprompt ]; then
  printf 'Press Enter to close this window. '
  read -r _ANSWER
fi
exit "$RC"
