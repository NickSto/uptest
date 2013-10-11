#!/usr/bin/env bash
SLEEP_DEFAULT=15
USAGE="USAGE: $(basename $0) [sleep seconds]
  e.g. $(basename $0) 10
default sleep: 15 sec"
sleep=$SLEEP_DEFAULT
if [ "$1" ]; then
  if [[ "$1" =~ ^[0-9]+$ ]]; then
    sleep="$1"
  else
    echo "$USAGE"
    exit 1
  fi
fi

while [ 1 ]; do
  last=$(date +%s)
  sleeptime=$sleep
  humantime=$(date '+%Y-%m-%d %H:%M:%S')
  response=$(ping -n -c 1 google.com 2>/dev/null | grep 'bytes from')
  if [ ${#response} -gt 0 ]; then
    dest=$(echo $response | sed -E 's/^.*from ([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+): .*$/\1/')
    ms=$(echo $response | sed 's/^[0-9]\+ bytes from.*icmp_req=[0-9]\+ ttl=[0-9]\+ time=\(.*\)$/\1/')
    result="$ms\tfrom $dest"
  else
    result="**********DROPPED**********"
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
