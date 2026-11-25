#!/bin/bash
# MAD STAY guard: keep the supervisor itself alive.
#
# A cron job fires this every 5 minutes. If stay.py is running, exit
# silently. If it is not, start it detached and print one line saying
# so. stay.py takes a lockfile, so even a racy double start is safe:
# the second copy stands down.
if pgrep -f "stay[.]py" >/dev/null 2>&1; then
  exit 0
fi
cd "$HOME/workspace/mad-stay" || exit 1
setsid nohup /usr/bin/python3 stay.py >> stay.out 2>&1 &
echo "MAD STAY was down — guard restarted the supervisor (pid $!)"
