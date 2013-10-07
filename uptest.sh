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
  sleeptime=$sleep
  response=$(ping -c 1 google.com 2>/dev/null | grep 'bytes from')
  if [ ${#response} -gt 0 ]; then
    dest=$(echo $response | sed 's/^64 bytes from \(.*\)icmp_req=[0-9]\+ ttl=[0-9]\+ time=.*$/\1/')
    ms=$(echo $response | sed 's/^64 bytes from.*icmp_req=[0-9]\+ ttl=[0-9]\+ time=\(.*\)$/\1/')
    echo -ne "$dest\t$ms\t"
  else
    echo -ne "**********************DROPPED**********************\t"
    sleeptime=5
  fi
  while [ $sleeptime -gt 0 ]; do
    echo -n '*'
    sleep 1
    sleeptime=$((sleeptime-1))
  done
  echo -ne "\n"
done
