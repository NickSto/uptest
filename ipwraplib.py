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
  iwconfig_cmd = 'iwconfig'
  # Check if iwconfig command is available. If not, fall back to the common absolute path
  # /sbin/iwconfig. If this doesn't exist, subprocess will return an OSError anyway.
  # Note: distutils.spawn.find_executable() fails with an exception if there is no $PATH defined.
  # So we'll check first for that scenario. (I've actually seen this, for instance in the
  # environment NetworkManager sets up for scripts in /etc/NetworkManager/dispatcher.d/.
  if 'PATH' not in os.environ or not distutils.spawn.find_executable(iwconfig_cmd):
    iwconfig_cmd = '/sbin/iwconfig'
  # Call iwconfig.
  devnull = open(os.devnull, 'w')
  try:
    output = subprocess.check_output([iwconfig_cmd], stderr=devnull)
  except (OSError, subprocess.CalledProcessError):
    return (None, None, None)
  finally:
    devnull.close()
  # Parse ssid and mac from output.
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
  ip_cmd = 'ip'
  # Check if 'ip' command is available. If not, fall back to common absolute path.
  if 'PATH' not in os.environ or not distutils.spawn.find_executable(ip_cmd):
    ip_cmd = '/sbin/ip'
  # Call 'ip route show'.
  devnull = open(os.devnull, 'w')
  try:
    output = subprocess.check_output([ip_cmd, 'route', 'show'], stderr=devnull)
  except (OSError, subprocess.CalledProcessError):
    return (None, None)
  finally:
    devnull.close()
  # Parse output.
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
  dig_cmd = 'dig'
  if 'PATH' not in os.environ or not distutils.spawn.find_executable(dig_cmd):
    dig_cmd = '/usr/bin/dig'
  devnull = open(os.devnull, 'w')
  try:
    output = subprocess.check_output([dig_cmd, '+short', '+time=1', '+tries=2', domain],
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
  arp_cmd = 'arp'
  if 'PATH' not in os.environ or not distutils.spawn.find_executable(arp_cmd):
    arp_cmd = '/usr/sbin/arp'
  devnull = open(os.devnull, 'w')
  try:
    output = subprocess.check_output([arp_cmd, '-a'], stderr=devnull)
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
  # uuid.getnode() returns the MAC as an integer.
  mac_hex = hex(uuid.getnode())
  # [2:] removes leading '0x'.
  mac_hex = mac_hex[2:]
  # Fill in leading 0's, if needed.
  mac_hex = ('0' * (13 - len(mac_hex))) + mac_hex
  # Remove trailing 'L'.
  mac_hex = mac_hex[:12]
  # Build mac from characters in mac_hex, inserting colons.
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
