#!/bin/bash
# ci-run.sh COMMAND...: runs the command and, if it fails, copies the error lines of its output into an annotation (CI_NOTICE=1: the last lines of a success too). The logs of a
# run are shown only to someone signed in to GitHub, annotations to anyone: `gh api repos/OWNER/REPO/check-runs/JOB_ID/annotations` reads them with no token.
log="${TMPDIR:-/tmp}/ci-step.log"
"$@" > "$log" 2>&1
status=$?
cat "$log"
[ -n "$CI_NOTICE" ] && echo "::notice title=$* (exit $status)::$({ grep -E 'checks|: ok|tells names' "$log"; tail -n 4 "$log"; } | sed 's/%/%25/g' | awk '{printf "%s%%0A", $0}')"
if [ "$status" -ne 0 ]; then
  msg=$(grep -E 'error|undefined|Error|cannot|not found|FAIL|unexpected' "$log" | head -40 | sed 's/%/%25/g' | awk '{printf "%s%%0A", $0}')
  echo "::error title=$* failed (exit $status)::$msg"
fi
exit $status
