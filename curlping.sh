#!/usr/bin/env bash
set -ue
server="google.com"
if [[ $# -gt 0 ]]; then
  server=$1
fi

while [[ 1 ]]; do
  curl_sec=$(curl -s --write-out '%{time_connect}\n' --output /dev/null "$server")
  curl=$(echo "1000*$curl_sec" | bc)
  ping=$(ping -c 1 -n -W 2 "$server" | sed -En 's/^[0-9]+ bytes from.*icmp_req=[0-9]+ ttl=[0-9]+ time=([0-9.]+) ms$/\1/p')
  diff=$(echo "$curl - $ping" | bc)
  echo -e "$ping\t$curl\t$diff"
done
