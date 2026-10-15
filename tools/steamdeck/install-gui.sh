#!/bin/sh
# install-gui.sh - install Pentamoor with no terminal: for the Steam Deck's desktop mode (KDE), and any Linux desktop.
#
#   tools/steamdeck/install-gui.sh               choose the disc image (.iso) in a file picker, install with a progress window, offer to add Pentamoor to Steam
#   tools/steamdeck/install-gui.sh --steam-only  only the "add to Steam" part
#   tools/steamdeck/install-gui.sh "disc.iso"    the same with the disc image given
#
# "Install Pentamoor.desktop" (beside this folder in the Steam Deck download) runs it on a double click.
#
# Dialogs: kdialog (KDE: the Deck's desktop mode), else zenity, else the questions are asked in a terminal. The progress is a kdialog progress bar (needs qdbus or dbus-send, which
# the Deck has), a zenity progress bar, or a Konsole/xterm window that shows the installer's own text; with none of them it runs in the background and logs to
# pentamoor-install.log. The installer is the one in this folder (pentamoor-install, a Python program): it reads the disc image, builds the game on this machine, and, with
# no C compiler (SteamOS has none), downloads one (Zig, about 100 MB) into this folder. SteamOS keeps / read-only: nothing is installed system-wide, nothing is written
# outside this folder (and ~/.local/share/applications and Steam's own files, when you say yes to adding Pentamoor to Steam).
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

# run_installer ISO RCFILE: runs the installer and writes its exit status to RCFILE, showing progress the best way there is
run_installer() {
  ISO=$1; RCFILE=$2
  : > "$LOG"
  if [ "$DLG" = kdialog ] && [ -n "$DBUS" ]; then
    REF=$(kdialog --title "$TITLE" --progressbar "Starting the installer..." 100)
    PB_SVC=${REF%% *}                # kdialog prints "org.kde.kdialog-1234 /ProgressDialog"
    PB_PATH=${REF#* }
    case $REF in *" "*) ;; *) PB_SVC=''; PB_PATH='' ;; esac
    if [ -n "$PB_SVC" ] && [ -n "$PB_PATH" ]; then
      { "$PY" "$ROOT/pentamoor-install" --yes --clean "$ISO" 2>&1; echo $? > "$RCFILE"; } | "$PY" "$HERE/progress.py" --log "$LOG" |
        while IFS='|' read -r PCT LABEL; do pb_set "$PCT"; pb_label "$LABEL"; done
      pb_close
      return 0
    fi
  fi
  if [ "$DLG" = zenity ]; then
    { "$PY" "$ROOT/pentamoor-install" --yes --clean "$ISO" 2>&1; echo $? > "$RCFILE"; } | "$PY" "$HERE/progress.py" --log "$LOG" |
      while IFS='|' read -r PCT LABEL; do printf '# %s\n%s\n' "$LABEL" "$PCT"; done |
      zenity --progress --title "$TITLE" --text "Starting the installer..." --percentage 0 --auto-close --no-cancel --width 480
    return 0
  fi
  # a terminal window that shows the installer's own text
  if [ -t 1 ]; then
    sh "$HERE/install-run.sh" "$ISO" "$RCFILE" noprompt
    return 0
  fi
  if [ -n "${DISPLAY}${WAYLAND_DISPLAY}" ]; then
    if have konsole; then konsole --nofork -e sh "$HERE/install-run.sh" "$ISO" "$RCFILE"; return 0; fi
    if have xterm; then xterm -e sh "$HERE/install-run.sh" "$ISO" "$RCFILE"; return 0; fi
  fi
  # nothing to show it in: it runs, and the log says how it went
  { "$PY" "$ROOT/pentamoor-install" --yes --clean "$ISO" 2>&1; echo $? > "$RCFILE"; } > "$LOG"
  return 0
}

# ---- adding to Steam -------------------------------------------------------------------------------------------------------------------------------------
steam_is_running() { "$PY" "$HERE/add-to-steam.py" --check-steam >/dev/null 2>&1; [ $? -eq 3 ]; }

add_to_steam() {
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
  OUT=$("$PY" "$HERE/add-to-steam.py" --desktop-entry --controller-template 2>&1)
  RC=$?
  if [ $RC -ne 0 ]; then
    err "Pentamoor could not be added to Steam automatically:

$OUT"
    return 0
  fi
  msg "Pentamoor is added to Steam.

$OUT

In Gaming Mode: Library > Non-Steam (or All Games) > Pentamoor. Then press the controller button and pick the Pentamoor (or Gamepad) layout; see docs/notes/steamdeck.md."
  if [ "${RESTART:-0}" = 1 ] && have steam && ask "Start Steam again now?"; then
    nohup steam >/dev/null 2>&1 &
  fi
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

if [ "$1" = "--steam-only" ]; then
  add_to_steam
  exit 0
fi

ISO=
case $1 in *.iso|*.ISO) ISO=$1 ;; esac

INSTALLED=0
if [ -f "$ROOT/sources/installed/Magic/Program/MAGIC.EXE" ] && { [ -f "$ROOT/game_magic.so" ] || [ -f "$ROOT/src/port/build/game_magic.so" ]; }; then INSTALLED=1; fi
if [ $INSTALLED = 1 ] && [ -z "$ISO" ]; then
  msg "Pentamoor is already installed in
$ROOT"
  if ask "Add it to Steam (so it shows up in Gaming Mode)?"; then add_to_steam; fi
  exit 0
fi

FREE_KB=$(df -Pk "$ROOT" 2>/dev/null | awk 'NR==2 {print $4}')
if [ -n "$FREE_KB" ] && [ "$FREE_KB" -lt $NEED_KB ] 2>/dev/null; then
  err "There is not enough free disk space for the install: about 1.2 GB is needed, $((FREE_KB / 1024)) MB is free where this folder is ($ROOT)."
  exit 1
fi

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

RCFILE=$(mktemp "${TMPDIR:-/tmp}/pentamoor-rc.XXXXXX") || exit 1
run_installer "$ISO" "$RCFILE"
RC=$(cat "$RCFILE" 2>/dev/null)
rm -f "$RCFILE"

if [ "$RC" != 0 ] || { [ ! -f "$ROOT/game_magic.so" ] && [ ! -f "$ROOT/src/port/build/game_magic.so" ]; }; then
  err "The installation did not finish (exit status ${RC:-unknown}).

The end of the installer's output:
$(tail -n 12 "$LOG" 2>/dev/null)

The whole of it is in $LOG. A disc image of another version of the game, or not enough space, are the usual causes."
  exit 1
fi

msg "Pentamoor is installed. Start it with ./pentamoor in the folder, or add it to Steam next."
if ask "Add Pentamoor to Steam (so it shows up in Gaming Mode, with its controller layout)?"; then add_to_steam; fi
exit 0
