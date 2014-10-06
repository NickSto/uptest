#!/usr/bin/env bash
# Testing how well ping and curl latency correlates.
# So far, the relationship is linear, following curl = ping*1.0366 - 6.5
# awkt 'BEGIN {tol=15; a1=-6.5; b1=1.0366; a2=4; b2=1} {total++; y1=$1*b1+a1; y2=$1*b2+a2} (y1 < $2+tol && y1 > $2-tol) || (y2 < $2+tol && y2 > $2-tol) {pass++} END {print pass, total, 100*pass/total}' curlping.log

DATA_DIR="$HOME/.local/share/nbsdata"
SILENCE="$DATA_DIR/SILENCE"
ASN_CACHE="$DATA_DIR/asn-cache.tsv"
SLEEPTIME=5 #seconds
SERVER='nsto.co'
CURLPATH='/misc/access.txt'

function main {
  echo -n > /tmp/ping.txt
  echo -n > /tmp/curl.txt
  lan_ip=''
  while true; do
    pingms=$(cat /tmp/ping.txt)
    curls=$(cat /tmp/curl.txt)
    interface=$(ip route show | sed -En 's/^default .* dev ([a-zA-Z0-9:_-]+) .*$/\1/p')
    lan_ip_current=$(dev_ip $interface)
    if [[ $lan_ip != $lan_ip_current ]]; then
      lan_ip="$lan_ip_current"
      asn=$(get_asn "$lan_ip")
    fi
    if [[ $pingms ]] && [[ $curls ]]; then
      curlms=$(echo "$curls*1000" | bc)
      echo -e "$pingms\t$curlms\t$asn\t$interface"
    fi
    echo -n > /tmp/ping.txt
    echo -n > /tmp/curl.txt
    ping -n -c 1 $SERVER | sed -En 's/^.* bytes from .* time=([0-9.]+) ?ms.*$/\1/p' > /tmp/ping.txt &
    curl -s --write-out '%{time_connect}\n' --output /dev/null $SERVER$CURLPATH > /tmp/curl.txt &
    sleep $SLEEPTIME
  done
}

function dev_ip {
  query="$1"
  last=""
  ifconfig | while read line; do
    if [[ ! "$last" ]]; then
      dev=$(echo "$line" | sed -r 's/^(\S+)\s+.*$/\1/g')
    fi
    if [[ $dev != $query ]]; then
      continue
    fi
    if [[ "$line" =~ 'inet addr' ]]; then
      echo "$line" | sed -r 's/^\s*inet addr:\s*([0-9.]+)\s+.*$/\1/g'
    fi
    last=$line
  done
}

function get_asn {
  wan_ip=$(curl -s ipv4.icanhazip.com)
  asn=$(awk -F '\t' '$1 == "'$wan_ip'" {print $2}' $ASN_CACHE | head -n 1)
  if [[ ! $asn ]]; then
    asn=$(curl -s http://ipinfo.io/$wan_ip/org | grep -Eo '^AS[0-9]+')
    if [[ $asn ]]; then
      echo -e "$wan_ip\t$asn" >> $ASN_CACHE
    fi
  fi
  echo $asn
}

main "$@"
