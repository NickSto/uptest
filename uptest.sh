#!/usr/bin/env bash
SILENCE="$HOME/.local/share/nbsdata/SILENCE"
SLEEP_DEFAULT=5
LOGFILE_DEFAULT="$HOME/.local/share/nbsdata/uptest.log"
USAGE="USAGE: $(basename $0) [sleep seconds [-l [log]]]
  e.g. $(basename $0) 10 -l log.txt
sleep seconds: Optional, default is $SLEEP_DEFAULT seconds.
-l: Optional, default is no logging. Sleep seconds must be given if -l is.
    If -l is given alone, it will log to the default file:
    $LOGFILE_DEFAULT
    If a filename is given after -l, it will log to that file.
    If silence file named "$SILENCE" exists, it will stop
    logging until it is gone."
sleep=$SLEEP_DEFAULT
logfile=$LOGFILE_DEFAULT
if [ "$1" ]; then
  if [[ "$1" =~ ^[0-9]+$ ]]; then
    sleep="$1"
  else
    echo "$USAGE"
    exit 1
  fi
fi
if [ "$2" ] && [ "$2" == "-l" ]; then
  log="true"
  if [ "$3" ]; then
    logfile="$3"
  fi
  echo "Logging to file $logfile"
fi

while [ 1 ]; do
  last=$(date +%s)
  sleeptime=$sleep
  if [[ -f "$SILENCE" ]]; then
    echo "Silence file $SILENCE exists. Skipping ping.."
    sleep $sleeptime
    continue
  fi
  humantime=$(date '+%Y-%m-%d %H:%M:%S')
  response=$(ping -n -c 1 -W 4 google.com 2>/dev/null | grep 'bytes from')
  # todo: decide success based on the summary line ("1 received")
  if [ ${#response} -gt 0 ]; then
    dest=$(echo $response | sed -E 's/^.*from ([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+): .*$/\1/')
    ms=$(echo $response | sed -E 's/^[0-9]+ bytes from.*icmp_req=[0-9]+ ttl=[0-9]+ time=([0-9.]+) ms$/\1/')
    if [[ ! $ms =~ [0-9.]{1,6} ]]; then
      echo -e "Error: time regex failed to match line:\n$response" 1>&2
      ms=0
    fi
    result="$ms ms\tfrom $dest"
    logline="$ms\t$last"
  else
    result="**********DROPPED**********"
    logline="0\t$last"
    #sleeptime=5
  fi
  
  now=$(date +%s)
  elapsed=$((now - last))
  ratio=$((elapsed/sleeptime))
  #echo -n "start: $elapsed "
  if [ $ratio -eq 0 ]; then
    ratio=1
  fi
  while [ $ratio -gt 0 ]; do
    echo -ne "$result\t$humantime\t"
    if [ "$log" ]; then
      echo -e "$logline" >> "$logfile"
    fi
    ratio=$((ratio-1))
    if [ $ratio -gt 0 ]; then
      echo
    fi
  done

  while [ $elapsed -lt $sleeptime ]; do
    echo -n '*'
    sleep 1
    now=$(date +%s)
    elapsed=$((now - last))
  done
  echo -ne "\n"
done
