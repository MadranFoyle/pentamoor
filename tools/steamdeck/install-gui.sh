#!/bin/sh
# install-gui.sh - install Pentamoor with no terminal: for the Steam Deck's desktop mode (KDE), and any Linux desktop.
#
#   tools/steamdeck/install-gui.sh               choose the disc image (.iso) in a file picker, install with a progress window, then offer Spells of the Ancients 2.15 (optional: its
#                                                disc image and the 2.15 patch, two more file pickers) and adding Pentamoor to Steam
#   tools/steamdeck/install-gui.sh --steam-only  only the "add to Steam" part (with a second shortcut for Spells of the Ancients when that is installed)
#   tools/steamdeck/install-gui.sh --sota        only the Spells of the Ancients part, for a Pentamoor that is installed already (when it is not, the first game's install comes first)
#   tools/steamdeck/install-gui.sh "disc.iso"    the first install with the disc image given
#
# "Install Pentamoor.desktop", "Install Spells of the Ancients.desktop" and "Add Pentamoor to Steam.desktop" (beside this folder in the Steam Deck download) run it on a double click.
#
# Dialogs: kdialog (KDE: the Deck's desktop mode), else zenity, else the questions are asked in a terminal. The progress is a kdialog progress bar (needs qdbus or dbus-send, which
# the Deck has), a zenity progress bar, or a Konsole/xterm window that shows the installer's own text; with none of them it runs in the background and logs to
# pentamoor-install.log. The installer is the one in this folder (pentamoor-install, a Python program): it reads the disc image, builds the game on this machine, and, with
# no C compiler (SteamOS has none), downloads one (Zig, about 100 MB) into this folder. SteamOS keeps / read-only: nothing is installed system-wide, nothing is written
# outside this folder (and ~/.local/share/applications and Steam's own files, when you say yes to adding Pentamoor to Steam).
#
# Spells of the Ancients: the installer is given --sota DISC --patch FILE (the command line of the README). Before that it is run once with --verify-only, which makes the checks an install
# makes first (the right disc, the whole patch: a cut-short one is refused with the installer's own message) and writes nothing, so a wrong file is told at once and can be chosen again.
#
# The one thing that cannot be checked without a Steam Deck: how the dialogs look there. The sequence of calls is tested (tools/steamdeck/test_steamdeck.py).

HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd) || exit 1
ROOT=$(CDPATH='' cd -- "$HERE/../.." && pwd) || exit 1
cd "$ROOT" || exit 1
TITLE="Pentamoor"
LOG="$ROOT/pentamoor-install.log"
NEED_KB=1258291            # 1.2 GB: what it needs while it builds (1 GB, and room to spare)

have() { command -v "$1" >/dev/null 2>&1; }

PY=$(command -v python3 || command -v python)

# where things are once installed: the launcher's own rules (the ./pentamoor script): the first game's module is game_magic, Spells of the Ancients' are game_shandalar (the adventure) and game_shell
SOTA_DIR=${PENTAMOOR_SOTA:-$ROOT/sources/installed_sota/Magic/Program}
module_built() { [ -f "$ROOT/$1.so" ] || [ -f "$ROOT/src/port/build/$1.so" ] || [ -f "$ROOT/$1.dylib" ] || [ -f "$ROOT/src/port/build/$1.dylib" ]; }     # (.dylib: a Mac, where this runs when it is tried)
first_installed() { [ -f "$ROOT/sources/installed/Magic/Program/MAGIC.EXE" ] && module_built game_magic; }
sota_installed() { [ -f "$SOTA_DIR/shandalar.exe" ] && module_built game_shandalar; }
sota_shell_installed() { [ -f "$SOTA_DIR/magic.exe" ] && module_built game_shell; }

# ---- which dialogs ---------------------------------------------------------------------------------------------------------------------------------------
DLG=none
if [ -n "${DISPLAY}${WAYLAND_DISPLAY}" ]; then
  if have kdialog; then DLG=kdialog; elif have zenity; then DLG=zenity; fi
fi

# kdialog shows its text as rich text when it looks like it; a plain text with real line breaks is shown as written
msg() {
  case $DLG in
    kdialog) kdialog --title "$TITLE" --msgbox "$1" ;;
    zenity) zenity --info --title "$TITLE" --no-markup --width 480 --text "$1" ;;
    *) printf '%s\n' "$1" ;;
  esac
}

err() {
  case $DLG in
    kdialog) kdialog --title "$TITLE" --error "$1" ;;
    zenity) zenity --error --title "$TITLE" --no-markup --width 480 --text "$1" ;;
    *) printf '%s\n' "$1" >&2 ;;
  esac
}

ask() {      # yes (0) or no (1)
  case $DLG in
    kdialog) kdialog --title "$TITLE" --yesno "$1" ;;
    zenity) zenity --question --title "$TITLE" --no-markup --width 480 --text "$1" ;;
    *)
      printf '%s [Y/n] ' "$1"
      read -r ANSWER || return 1
      case $ANSWER in n*|N*) return 1 ;; esac
      return 0 ;;
  esac
}

pick_iso() {     # prints the chosen path; nothing if cancelled
  START=$HOME
  [ -d "$HOME/Downloads" ] && START=$HOME/Downloads
  case $DLG in
    kdialog)
      kdialog --title "Choose the Magic: The Gathering disc image (.iso)" --getopenfilename "$START" "*.iso *.ISO|Disc images (*.iso)
*|All files" ;;
    zenity)
      zenity --file-selection --title "Choose the Magic: The Gathering disc image (.iso)" --filename "$START/" \
        --file-filter "Disc images | *.iso *.ISO" --file-filter "All files | *" ;;
    *)
      printf 'Path of the disc image (.iso) of the retail Magic: The Gathering CD, version 1.0 (empty to cancel): ' >&2
      read -r P || return 0
      P=${P#\"}; P=${P%\"}; P=${P#\'}; P=${P%\'}
      printf '%s\n' "$P" ;;
  esac
}

# the pickers of Spells of the Ancients' two files start in the folder the first file came from (LASTDIR), else where the first picker did
pick_sota_iso() {     # prints the chosen path; nothing if cancelled
  START=$HOME
  [ -d "$HOME/Downloads" ] && START=$HOME/Downloads
  [ -n "$LASTDIR" ] && [ -d "$LASTDIR" ] && START=$LASTDIR
  case $DLG in
    kdialog)
      kdialog --title "Choose the Spells of the Ancients disc image (.iso)" --getopenfilename "$START" "*.iso *.ISO|Disc images (*.iso)
*|All files" ;;
    zenity)
      zenity --file-selection --title "Choose the Spells of the Ancients disc image (.iso)" --filename "$START/" \
        --file-filter "Disc images | *.iso *.ISO" --file-filter "All files | *" ;;
    *)
      printf 'Path of the disc image (.iso) of the Spells of the Ancients CD, version 2.0, often named MTG v2.00.iso (empty to cancel): ' >&2
      read -r P || return 0
      P=${P#\"}; P=${P%\"}; P=${P#\'}; P=${P%\'}
      printf '%s\n' "$P" ;;
  esac
}

pick_patch() {     # prints the chosen path; nothing if cancelled
  START=$HOME
  [ -d "$HOME/Downloads" ] && START=$HOME/Downloads
  [ -n "$LASTDIR" ] && [ -d "$LASTDIR" ] && START=$LASTDIR
  case $DLG in
    kdialog)
      kdialog --title "Choose the 2.15 patch (SOTAV215.EXE)" --getopenfilename "$START" "*.exe *.EXE|Programs (*.exe)
*|All files" ;;
    zenity)
      zenity --file-selection --title "Choose the 2.15 patch (SOTAV215.EXE)" --filename "$START/" \
        --file-filter "Programs | *.exe *.EXE" --file-filter "All files | *" ;;
    *)
      printf 'Path of the Spells of the Ancients 2.15 patch, the whole file SOTAV215.EXE (empty to cancel): ' >&2
      read -r P || return 0
      P=${P#\"}; P=${P%\"}; P=${P#\'}; P=${P%\'}
      printf '%s\n' "$P" ;;
  esac
}

# ---- progress --------------------------------------------------------------------------------------------------------------------------------------------
DBUS=
for q in qdbus qdbus-qt5 qdbus6 qdbus-qt6; do
  if have "$q"; then DBUS=$q; break; fi
done
if [ -z "$DBUS" ] && have dbus-send; then DBUS=dbus-send; fi

PB_SVC=''
PB_PATH=''
pb_set() {       # percent
  case $DBUS in
    dbus-send) dbus-send --session --type=method_call --dest="$PB_SVC" "$PB_PATH" org.freedesktop.DBus.Properties.Set string:"" string:value variant:int32:"$1" >/dev/null 2>&1 ;;
    "") ;;
    *) "$DBUS" "$PB_SVC" "$PB_PATH" Set "" value "$1" >/dev/null 2>&1 ;;
  esac
}
pb_label() {     # text
  case $DBUS in
    dbus-send) dbus-send --session --type=method_call --dest="$PB_SVC" "$PB_PATH" org.kde.kdialog.ProgressDialog.setLabelText string:"$1" >/dev/null 2>&1 ;;
    "") ;;
    *) "$DBUS" "$PB_SVC" "$PB_PATH" setLabelText "$1" >/dev/null 2>&1 ;;
  esac
}
pb_close() {
  case $DBUS in
    dbus-send) dbus-send --session --type=method_call --dest="$PB_SVC" "$PB_PATH" org.kde.kdialog.ProgressDialog.close >/dev/null 2>&1 ;;
    "") ;;
    *) "$DBUS" "$PB_SVC" "$PB_PATH" close >/dev/null 2>&1 ;;
  esac
}

# run_installer RCFILE ARGS...: runs the installer (with --yes --clean and ARGS) and writes its exit status to RCFILE, showing progress the best way there is.
# (progress.py follows the Spells of the Ancients run by the installer's own lines: its first steps are other ones.)
run_installer() {
  RCFILE=$1; shift
  : > "$LOG"
  if [ "$DLG" = kdialog ] && [ -n "$DBUS" ]; then
    REF=$(kdialog --title "$TITLE" --progressbar "Starting the installer..." 100)
    PB_SVC=${REF%% *}                # kdialog prints "org.kde.kdialog-1234 /ProgressDialog"
    PB_PATH=${REF#* }
    case $REF in *" "*) ;; *) PB_SVC=''; PB_PATH='' ;; esac
    if [ -n "$PB_SVC" ] && [ -n "$PB_PATH" ]; then
      { "$PY" "$ROOT/pentamoor-install" --yes --clean "$@" 2>&1; echo $? > "$RCFILE"; } | "$PY" "$HERE/progress.py" --log "$LOG" |
        while IFS='|' read -r PCT LABEL; do pb_set "$PCT"; pb_label "$LABEL"; done
      pb_close
      return 0
    fi
  fi
  if [ "$DLG" = zenity ]; then
    { "$PY" "$ROOT/pentamoor-install" --yes --clean "$@" 2>&1; echo $? > "$RCFILE"; } | "$PY" "$HERE/progress.py" --log "$LOG" |
      while IFS='|' read -r PCT LABEL; do printf '# %s\n%s\n' "$LABEL" "$PCT"; done |
      zenity --progress --title "$TITLE" --text "Starting the installer..." --percentage 0 --auto-close --no-cancel --width 480
    return 0
  fi
  # a terminal window that shows the installer's own text
  if [ -t 1 ]; then
    sh "$HERE/install-run.sh" "$RCFILE" noprompt "$@"
    return 0
  fi
  if [ -n "${DISPLAY}${WAYLAND_DISPLAY}" ]; then
    if have konsole; then konsole --nofork -e sh "$HERE/install-run.sh" "$RCFILE" prompt "$@"; return 0; fi
    if have xterm; then xterm -e sh "$HERE/install-run.sh" "$RCFILE" prompt "$@"; return 0; fi
  fi
  # nothing to show it in: it runs, and the log says how it went
  { "$PY" "$ROOT/pentamoor-install" --yes --clean "$@" 2>&1; echo $? > "$RCFILE"; } > "$LOG"
  return 0
}

# ---- adding to Steam -------------------------------------------------------------------------------------------------------------------------------------
steam_is_running() { "$PY" "$HERE/add-to-steam.py" --check-steam >/dev/null 2>&1; [ $? -eq 3 ]; }

# STEAM_SOTA: yes (already decided: add Spells of the Ancients' shortcut too), no, or empty (ask, when Spells of the Ancients is installed)
STEAM_SOTA=

add_to_steam() {
  SOTA_ARG=
  if sota_shell_installed; then
    if [ "$STEAM_SOTA" = yes ]; then
      SOTA_ARG=--sota
    elif [ "$STEAM_SOTA" != no ] && ask "Spells of the Ancients 2.15 is installed too. Add it to Steam as well?

It gets a shortcut of its own, \"Pentamoor: Spells of the Ancients\", that starts the Magic Shell (a menu of single duels, gauntlets and sealed decks; its World page starts the adventure). The first game keeps its own shortcut."; then
      SOTA_ARG=--sota
    fi
  fi
  if steam_is_running; then
    if ask "Steam is running, and it must be closed to add a game (it writes its list of games again when it quits).

Close Steam now? It starts again when you switch to Gaming Mode, or from the application menu."; then
      have steam && steam -shutdown >/dev/null 2>&1
      N=0
      while steam_is_running && [ $N -lt 60 ]; do sleep 1; N=$((N + 1)); done
    else
      return 0
    fi
    if steam_is_running; then
      err "Steam is still running. Close it (Steam menu > Exit), then run \"Add Pentamoor to Steam\" again."
      return 0
    fi
    RESTART=1
  fi
  OUT=$("$PY" "$HERE/add-to-steam.py" --desktop-entry --controller-template $SOTA_ARG 2>&1)
  RC=$?
  if [ $RC -ne 0 ]; then
    err "Pentamoor could not be added to Steam automatically:

$OUT"
    return 0
  fi
  if [ -n "$SOTA_ARG" ]; then
    msg "Pentamoor and Pentamoor: Spells of the Ancients are added to Steam.

$OUT

In Gaming Mode: Library > Non-Steam (or All Games) > Pentamoor, and Pentamoor: Spells of the Ancients. For each of them press the controller button and pick the Pentamoor (or Gamepad) layout; see docs/notes/steamdeck.md."
  else
    msg "Pentamoor is added to Steam.

$OUT

In Gaming Mode: Library > Non-Steam (or All Games) > Pentamoor. Then press the controller button and pick the Pentamoor (or Gamepad) layout; see docs/notes/steamdeck.md."
  fi
  if [ "${RESTART:-0}" = 1 ] && have steam && ask "Start Steam again now?"; then
    nohup steam >/dev/null 2>&1 &
  fi
  return 0
}

# ---- Spells of the Ancients ------------------------------------------------------------------------------------------------------------------------------
LASTDIR=
SOTA_FAILED=
GIVEN_SOTA=
GIVEN_PATCH=

enough_space() {     # WHAT: tells the person when there is not enough room for the install
  FREE_KB=$(df -Pk "$ROOT" 2>/dev/null | awk 'NR==2 {print $4}')
  if [ -n "$FREE_KB" ] && [ "$FREE_KB" -lt $NEED_KB ] 2>/dev/null; then
    err "There is not enough free disk space for $1: about 1.2 GB is needed while it works, $((FREE_KB / 1024)) MB is free where this folder is ($ROOT)."
    return 1
  fi
  return 0
}

# sota_step: the optional Spells of the Ancients install, for a Pentamoor that is installed. Asks, asks for the two files and checks them, installs with a progress window, and says what
# it did. Returns 0 when Spells of the Ancients is installed afterwards, 1 when it is not (declined, cancelled, failed: those have said so)
sota_step() {
  if ! ask "Spells of the Ancients (optional)

Spells of the Ancients is the 1997 expansion of the game. Pentamoor can build its last version, 2.15, beside the first game: a folder of its own, with its own saved games. That takes two files that you own, and you need both:

1. The disc image (.iso file) of the expansion's CD, Magic: The Gathering \"Spells of the Ancients\", version 2.0 (often named MTG v2.00.iso). It holds the game's files.
2. The 2.15 patch, SOTAV215.EXE (1,207,571 bytes). The CD is version 2.0; the patch brings it to 2.15. It has to be the whole file: the installer refuses one that was cut short, and says so.

The installer checks both before it writes anything. Because it has then checked your discs, it also sets the game's own \"skip the disc check\" flag, so the installed game does not ask for a disc later. (The original installer did not set that flag.)

It builds the game's programs again, so it takes about as long as the first install (2 to 15 minutes) and up to 1.2 GB of free space while it works; the expansion's files stay at about 310 MB. You can also do this later with \"Install Spells of the Ancients\" in this folder.

Install Spells of the Ancients now?"; then
    return 1
  fi
  enough_space "Spells of the Ancients" || return 1
  D2=$GIVEN_SOTA
  P2=$GIVEN_PATCH
  while :; do
    if [ -z "$D2" ]; then
      D2=$(pick_sota_iso)
      [ -z "$D2" ] && return 1
    fi
    LASTDIR=$(dirname -- "$D2")
    if [ -z "$P2" ]; then
      P2=$(pick_patch)
      [ -z "$P2" ] && return 1
    fi
    if [ ! -f "$D2" ] || [ ! -f "$P2" ]; then
      BAD=$D2; [ -f "$D2" ] && BAD=$P2
      err "$BAD is not a file."
      SOTA_FAILED=1
      D2=; P2=
      ask "Choose the files again?" || return 1
      continue
    fi
    # the installer's own checks, with nothing written: the right disc, the whole patch (a cut-short one is told here, in the installer's words)
    CHECK=$("$PY" "$ROOT/pentamoor-install" --verify-only --sota "$D2" --patch "$P2" 2>&1)
    if [ $? -eq 0 ]; then break; fi
    err "The installer checked the two files and cannot use them:

$(printf '%s\n' "$CHECK" | sed -n '/^install: /,$p' | sed 's/^install: //')"
    SOTA_FAILED=1
    D2=; P2=
    ask "Choose the files again?" || return 1
  done
  RCFILE=$(mktemp "${TMPDIR:-/tmp}/pentamoor-rc.XXXXXX") || return 1
  run_installer "$RCFILE" --sota "$D2" --patch "$P2"
  RC=$(cat "$RCFILE" 2>/dev/null)
  rm -f "$RCFILE"
  if [ "$RC" != 0 ] || ! sota_installed; then
    SOTA_FAILED=1
    err "Spells of the Ancients was not installed (exit status ${RC:-unknown}). The first game is not changed.

What the installer said:
$(grep '^install: ' "$LOG" 2>/dev/null | tail -n 3 | sed 's/^install: //')
$(tail -n 8 "$LOG" 2>/dev/null)

The whole of it is in $LOG."
    return 1
  fi
  msg "Spells of the Ancients 2.15 is installed, in
$SOTA_DIR

The discs and the patch were checked before anything was written, so the game does not ask for a disc when you play: the installer set the game's own \"skip the disc check\" flag. (The original installer did not set it.)

Start it with ./pentamoor sota shell (the Magic Shell; its World page starts the adventure) or ./pentamoor sota (the adventure itself). Its saved games are kept apart from the first game's."
  return 0
}

# ---- the steps -------------------------------------------------------------------------------------------------------------------------------------------
if [ -z "$PY" ]; then
  err "Python 3 was not found (the installer is a Python program). On a Steam Deck it is part of SteamOS; elsewhere install python3."
  exit 1
fi
if [ ! -f "$ROOT/pentamoor-install" ] || [ ! -f "$ROOT/tools/install/install.py" ]; then
  err "This does not look like an unpacked Pentamoor folder ($ROOT has no pentamoor-install). Unpack the whole download first, then run this again."
  exit 1
fi

MODE=install
ISO=
for A in "$@"; do
  case $A in
    --steam-only) MODE=steam ;;
    --sota) MODE=sota ;;
    *.iso|*.ISO) if [ "$MODE" = sota ]; then GIVEN_SOTA=$A; else ISO=$A; fi ;;
    *.exe|*.EXE) GIVEN_PATCH=$A ;;
  esac
done

if [ "$MODE" = steam ]; then
  add_to_steam
  exit 0
fi

if [ "$MODE" = sota ]; then
  if first_installed; then
    if sota_installed; then
      msg "Spells of the Ancients 2.15 is already installed in
$SOTA_DIR"
      if sota_shell_installed && ask "Add it to Steam (so it shows up in Gaming Mode)?"; then STEAM_SOTA=yes; add_to_steam; fi
      exit 0
    fi
    if sota_step; then
      if sota_shell_installed && ask "Add Spells of the Ancients to Steam (so it shows up in Gaming Mode, with its controller layout)?"; then STEAM_SOTA=yes; add_to_steam; fi
      exit 0
    fi
    [ -n "$SOTA_FAILED" ] && exit 1
    exit 0
  fi
  msg "Spells of the Ancients is installed over Pentamoor's first game, which is not installed yet. That comes first: this installs it now, and then asks about Spells of the Ancients."
fi

if first_installed && [ -z "$ISO" ]; then
  msg "Pentamoor is already installed in
$ROOT"
  if ! sota_installed; then
    msg "Spells of the Ancients 2.15 is not installed. To add it (it needs its disc image and the 2.15 patch), run \"Install Spells of the Ancients\" in this folder."
  fi
  if ask "Add it to Steam (so it shows up in Gaming Mode)?"; then add_to_steam; fi
  exit 0
fi

enough_space "the install" || exit 1

if ! ask "Pentamoor is a native port of the 1997 Magic: The Gathering (Shandalar). It needs your own copy of the game: a disc image (.iso file) of the retail CD, version 1.0.

The installer builds the game on this computer from your disc image. It takes about 2 to 15 minutes and up to 1 GB of disk space. This computer has no C compiler, so it downloads one (Zig, about 100 MB, checked against a known checksum) into this folder; nothing else is downloaded, and nothing outside this folder is changed.

Continue?"; then
  exit 0
fi

if [ -z "$ISO" ]; then
  ISO=$(pick_iso)
  if [ -z "$ISO" ]; then exit 0; fi
fi
if [ ! -f "$ISO" ]; then
  err "$ISO is not a file."
  exit 1
fi
LASTDIR=$(dirname -- "$ISO")

RCFILE=$(mktemp "${TMPDIR:-/tmp}/pentamoor-rc.XXXXXX") || exit 1
run_installer "$RCFILE" "$ISO"
RC=$(cat "$RCFILE" 2>/dev/null)
rm -f "$RCFILE"

if [ "$RC" != 0 ] || ! module_built game_magic; then
  err "The installation did not finish (exit status ${RC:-unknown}).

The end of the installer's output:
$(tail -n 12 "$LOG" 2>/dev/null)

The whole of it is in $LOG. A disc image of another version of the game, or not enough space, are the usual causes."
  exit 1
fi

msg "Pentamoor is installed. Start it with ./pentamoor in the folder, or add it to Steam next."
sota_step          # the optional second part (it asks first); a "no" or a failure leaves the first game as it is
if ask "Add Pentamoor to Steam (so it shows up in Gaming Mode, with its controller layout)?"; then add_to_steam; fi
exit 0
