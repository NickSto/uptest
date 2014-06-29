#!/usr/bin/env bash
set -u
DATA_DIR="$HOME/.local/share/nbsdata"
SILENCE="$DATA_DIR/SILENCE"
HISTORY="$DATA_DIR/uphistory.txt"
OUTPUT="$DATA_DIR/upsimple.txt"
SERVER="google.com"
SAMPLE_SIZE=5
SLEEP=5

hist_len=$((SAMPLE_SIZE-1))

# remove old lines from history file
function truncate {
  history=$1
  sample_size=$2
  sleep=$3
  now=$(date +%s)
  if [[ ! -f $history ]]; then
    return
  fi
  # the earliest timestamp to keep in the file
  cutoff=$((now-(sleep*(sample_size-1))))
  echo -n > "$history.tmp"
  # read each line, decide whether to keep by echoing into tmp file
  cat "$history" | while read line; do
    time=$(echo "$line" | cut -f 1)
    if [[ $time -ge $cutoff ]]; then
      echo "$line" >> "$history.tmp"
    fi
  done
  # replace original history file with tmp one
  mv "$history.tmp" "$history"
}

while [[ 1 ]]; do
  if [[ -f $SILENCE ]]; then
    sleep "$SLEEP"
    continue
  fi
  # truncate history file
  truncate "$HISTORY" "$SAMPLE_SIZE" "$SLEEP"
  # get current history
  if [[ -f $HISTORY ]]; then
    up=$(grep -c up "$HISTORY")
    down=$(grep -c down "$HISTORY")
  else
    up=0
    down=0
  fi
  # check connectivity
  if ping -c 1 -W 2 "$SERVER" >/dev/null 2>/dev/null; then
    up=$((up+1))
    echo -e "$now\tup" >> "$HISTORY"
  else
    down=$((down+1))
    echo -e "$now\tdown" >> "$HISTORY"
  fi
  # calculate percentage and write to output file
  pct=$((100*up/(up+down)))
  echo "$pct" > "$OUTPUT"
  sleep "$SLEEP"
done
