#!/bin/sh
# deploy.sh: put Pentamoor on an iPad (or in the iOS Simulator) with one command: check, sign, build, install, copy the game in, start it. docs/notes/ios.md, "One command".
#
#   ./deploy.sh --team ABCDE12345            the only iPad that is connected (USB or Wi-Fi paired); the team is optional when your keychain has one Apple Development certificate
#   ./deploy.sh --dry-run                    show every command, change nothing
#   ./deploy.sh --help                       all options (--device, --bundle-id, --no-data, --data-only, --logs, --console, --simulator ...)
#
# The work is in deploy.py (Python 3.9 is enough: /usr/bin/python3 on a Mac); this only finds a Python and hands over.
here=$(cd "$(dirname "$0")" && pwd)
for py in /usr/bin/python3 python3; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
    exec "$py" "$here/deploy.py" "$@"
  fi
done
echo "deploy.sh: no Python 3.8 or newer found. On a Mac, 'xcode-select --install' (or installing Xcode) provides /usr/bin/python3." >&2
exit 1
