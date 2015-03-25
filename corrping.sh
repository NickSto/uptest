#!/usr/bin/env bash
# Testing how well ping and curl latency correlates.
# So far, the relationship is linear, following curl = ping*1.0366 - 6.5
# awkt 'BEGIN {tol=15; a1=-6.5; b1=1.0366; a2=4; b2=1} {total++; y1=$1*b1+a1; y2=$1*b2+a2} (y1 < $2+tol && y1 > $2-tol) || (y2 < $2+tol && y2 > $2-tol) {pass++} END {print pass, total, 100*pass/total}' curlping.log

DATA_DIR="$HOME/.local/share/nbsdata"
SILENCE="$DATA_DIR/SILENCE"
ASN_CACHE="$DATA_DIR/asn-cache.tsv"
SLEEPTIME=5 #seconds
SERVER='www.gstatic.com'

function main {
  # Get script directory.
  if readlink -f dummy >/dev/null 2>/dev/null; then
    scriptdir=$(dirname $(readlink -f ${BASH_SOURCE[0]}))
  else
    echo "Error: readlink command required." >&2
    exit 1
  fi

  echo -n > ~/tmp/ping.txt
  echo -n > ~/tmp/curl.txt
  echo -n > ~/tmp/httplib.txt
  lan_ip=''
  while true; do
    # Get info about current connection.
    interface=$(ip route show | sed -En 's/^default .* dev ([a-zA-Z0-9:_-]+) .*$/\1/p')
    lan_ip_current=$(dev_ip $interface)
    if [[ $lan_ip != $lan_ip_current ]]; then
      lan_ip="$lan_ip_current"
      asn=$(get_asn "$lan_ip")
    fi
    # Collect data from last ping.
    ping_time=$(cat ~/tmp/ping.txt)
    curl_time=$(cat ~/tmp/curl.txt)
    httplib_time=$(cat ~/tmp/httplib.txt)
    if [[ $ping_time ]] && [[ $curl_time ]] && [[ $httplib_time ]]; then
      echo -e "$ping_time\t$curl_time\t$httplib_time\t$asn\t$interface"
    fi
    echo -n > ~/tmp/ping.txt
    echo -n > ~/tmp/curl.txt
    echo -n > ~/tmp/httplib.txt
    ping_wrap $SERVER > ~/tmp/ping.txt &
    curl_wrap $SERVER > ~/tmp/curl.txt &
    $scriptdir/httplib-ping.py > ~/tmp/httplib.txt &
    sleep $SLEEPTIME
  done
}

function ping_wrap {
  server="$1"
  ping -n -c 1 $server | sed -En 's/^.* bytes from .* time=([0-9.]+) ?ms.*$/\1/p'
}

function curl_wrap {
  server="$1"
  sec=$(curl -s --write-out '%{time_connect}\n' --output /dev/null $server)
  echo "$sec*1000" | bc
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
  if [[ $wan_ip ]]; then
    asn=$(awk -F '\t' '$1 == "'$wan_ip'" {print $2}' $ASN_CACHE | head -n 1)
    if [[ ! $asn ]]; then
      asn=$(curl -s http://ipinfo.io/$wan_ip/org | grep -Eo '^AS[0-9]+')
      if [[ $asn ]]; then
        echo -e "$wan_ip\t$asn" >> $ASN_CACHE
      fi
    fi
    echo $asn
  fi
}

main "$@"
