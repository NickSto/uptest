#!/usr/bin/env bash
# Testing how well ping and curl latency correlates.
# So far, the relationship is linear, following curl = ping*1.0366 - 6.5
# awkt 'BEGIN {tol=15; a1=-6.5; b1=1.0366; a2=4; b2=1} {total++; y1=$1*b1+a1; y2=$1*b2+a2} (y1 < $2+tol && y1 > $2-tol) || (y2 < $2+tol && y2 > $2-tol) {pass++} END {print pass, total, 100*pass/total}' curlping.log

SLEEPTIME=5 #seconds

echo -n > /tmp/ping.txt
echo -n > /tmp/curl.txt
while true; do
  pingms=$(cat /tmp/ping.txt)
  curls=$(cat /tmp/curl.txt)
  if [[ $pingms ]] && [[ $curls ]]; then
    echo -e "$pingms\t"$(echo "$curls*1000" | bc)
  fi
  echo -n > /tmp/ping.txt
  echo -n > /tmp/curl.txt
  ping -n -c 1 google.com | sed -En 's/^.* bytes from .* time=([0-9.]+) ?ms.*$/\1/p' > /tmp/ping.txt &
  curl -s --write-out '%{time_connect}\n' --output /dev/null google.com > /tmp/curl.txt &
  sleep $SLEEPTIME
done

