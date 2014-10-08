"""These functions are some simple wrappers for unix commands that query info
from the OS like wifi SSIDs, MAC addresses, DNS queries, etc."""
import os
import re
import uuid
import socket
import subprocess
import distutils.spawn

DEFAULT_ROUTE_REGEX = r'^default\s+via\s+((?:\d{1,3}\.){3}\d{1,3})\s+dev\s+(\S+)\s+\S+\s+\S+\s*$'
ARP_A_REGEX = r'^\S+\s+\(((?:\d{1,3}\.){3}\d{1,3})\)\s+at\s+((?:[0-9a-f]{2}:){5}[0-9a-f]{2})\s+\S+\s+on\s+\S+\s*$'


def get_wifi_info():
  """Find out what the wifi interface name, SSID and MAC address are.
  Returns those three values as strings, respectively. If you are not connected
  to wifi or if an error occurs, returns three None's.
  It currently does this by parsing the output from the 'iwconfig' command.
  It determines the data from the first section with fields for "SSID"
  (or "ESSID") and "Access Point" (case-insensitive)."""
  ssid = None
  mac = None
  interface = None
  # check if iwconfig command is available
  if not distutils.spawn.find_executable('iwconfig'):
    return (None, None, None)
  # call iwconfig
  devnull = open(os.devnull, 'w')
  try:
    output = subprocess.check_output(['iwconfig'], stderr=devnull)
  except (OSError, subprocess.CalledProcessError):
    return (ssid, mac)
  finally:
    devnull.close()
  # parse ssid and mac from output
  for line in output.splitlines():
    match = re.search(r'^(\S+)\s+\S', line)
    if match:
      interface = match.group(1)
    if not mac:
      match = re.search(r'^.*access point: ([a-fA-F0-9:]+)\s*$', line, re.I)
      if match:
        mac = match.group(1)
    if not ssid:
      match = re.search(r'^.*SSID:"(.*)"\s*$', line)
      if match:
        ssid = match.group(1)
    if ssid is not None and mac is not None:
      break
  return (interface, ssid, mac)


def get_default_route():
  """Determine the default networking interface in use at the moment by using
  the 'ip route show' command.
  Returns the name of the interface, and the IP of the default route. Or, on
  error, returns (None, None)."""
  interface = None
  ip = None
  # check if 'ip' command is available
  if not distutils.spawn.find_executable('ip'):
    return (None, None)
  # call 'ip route show'
  devnull = open(os.devnull, 'w')
  try:
    output = subprocess.check_output(['ip', 'route', 'show'], stderr=devnull)
  except (OSError, subprocess.CalledProcessError):
    return (None, None)
  finally:
    devnull.close()
  # parse output
  for line in output.splitlines():
    match = re.search(DEFAULT_ROUTE_REGEX, line)
    if match:
      ip = match.group(1)
      interface = match.group(2)
      break
  return (interface, ip)


def dig_ip(domain):
  """Use 'dig' command to get the first IP returned in a DNS query for 'domain'.
  On error, or no result, returns None."""
  ip = None
  if not distutils.spawn.find_executable('ip'):
    return None
  devnull = open(os.devnull, 'w')
  try:
    output = subprocess.check_output(['dig', '+short', '+time=1', '+tries=2',
                                      domain],
                                     stderr=devnull)
  except (OSError, subprocess.CalledProcessError):
    return None
  finally:
    devnull.close()
  for line in output.splitlines():
    ip = line.strip()
    return ip
  return None


def get_mac_from_ip(ip):
  """Use 'arp -a' command to look up the MAC address of an IP on the LAN.
  Returns None on error, or if the IP isn't found."""
  mac = None
  if not distutils.spawn.find_executable('arp'):
    return None
  devnull = open(os.devnull, 'w')
  try:
    output = subprocess.check_output(['arp', '-a'], stderr=devnull)
  except (OSError, subprocess.CalledProcessError):
    return None
  finally:
    devnull.close()
  for line in output.splitlines():
    match = re.search(ARP_A_REGEX, line)
    if match and match.group(1) == ip:
      mac = match.group(2)
      return mac.upper()
  return None


def get_mac():
  """Get your own device's MAC address using uuid.getnode().
  Returns the MAC formatted in standard hex with colons."""
  # uuid.getnode() returns the MAC as an integer
  mac_hex = hex(uuid.getnode())
  # [2:] removes leading '0x'
  mac_hex = mac_hex[2:]
  # fill in leading 0's, if needed
  mac_hex = ('0' * (13 - len(mac_hex))) + mac_hex
  # remove trailing 'L'
  mac_hex = mac_hex[:12]
  # build mac from characters in mac_hex, inserting colons
  mac = ''
  for (i, char) in enumerate(mac_hex):
    if i > 1 and i % 2 == 0:
      mac += ':'
    mac += char
  return mac


def get_ip():
  """Get this machine's IP address.
  Should return the actual one used to connect to public IP's, if multiple
  interfaces are being used."""
  #TODO: Use get_default_route() to determine correct interface, and directly
  #      query its IP instead of kludge of making a dummy connection.
  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  sock.connect(('8.8.8.8', 53))
  ip = sock.getsockname()[0]
  sock.close()
  return ip
