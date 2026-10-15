#!/bin/sh
# run_all.sh [MINUTES] [OUTDIR]: soak the three screen sizes at once (each its own game process, control pipe, overlay and log).
# Needs the installed game and the built port, as the port does (README). Summaries: OUTDIR/<size>/summary.txt, events: OUTDIR/<size>/events.jsonl.
here=$(cd "$(dirname "$0")" && pwd)
minutes=${1:-20}
out=${2:-/tmp/soak}
mkdir -p "$out"
for res in 640x480 800x600 1024x768; do
    python3 "$here/soak.py" --res "$res" --minutes "$minutes" --workdir "$out/$res" > "$out/$res.out" 2>&1 &
done
wait
cat "$out"/*/summary.txt
