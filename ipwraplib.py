"""These functions are some simple wrappers for unix commands that query info
from the OS like wifi SSIDs, MAC addresses, DNS queries, etc."""
import os
import re
import socket
import subprocess
import distutils.spawn


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
    fields = line.rstrip('\r\n').split()
    if len(fields) < 7:
      continue
    # Expect a line like:
    #   default via 10.21.160.1 dev wlan0  proto static
    if fields[0] == 'default' and fields[1] == 'via' and fields[3] == 'dev':
      ip = fields[2]
      interface = fields[4]
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


def dns_query(domain):
  """Use the socket module to do a DNS query.
  Returns None on failure instead of raising an exception (like socket.gaierror)."""
  #TODO: Looks like getaddrinfo() is the preferred way?
  try:
    return socket.gethostbyname(domain)
  except socket.error:
    return None


def get_arp_table(proc_path='/proc/net/arp'):
  """Get ARP table data from the /proc/net/arp pseudo-file.
  Returns a dict mapping IP addresses to ARP table entries. Each entry is a dict
  mapping field names to values. Fields: ip (str), hwtype (int), flags (int), mac
  (str), mask (str), interface (str)."""
  table = {}
  header = True
  with open(proc_path) as arp_table:
    for line in arp_table:
      # Skip the header.
      if header:
        header = False
        continue
      # Assume the file is whitespace-delimited.
      fields = line.rstrip('\r\n').split()
      try:
        ip, hwtype, flags, mac, mask, interface = fields
      except ValueError:
        continue
      try:
        mac = mac.upper()
        hwtype = int(hwtype, 16)
        flags = int(flags, 16)
      except ValueError:
        continue
      table[ip] = {'ip':ip, 'hwtype':hwtype, 'flags':flags, 'mac':mac, 'mask':mask,
                   'interface':interface}
  return table


def get_mac_from_ip(ip):
  """Look up the MAC address of an IP on the LAN, using the /proc/net/arp pseudo-file.
  Returns None if the IP isn't found."""
  arp_table = get_arp_table()
  if ip in arp_table:
    return arp_table[ip]['mac']
  else:
    return None


def get_ip():
  """Get this machine's local IP address.
  Should return the actual one used to connect to public IP's, if multiple
  interfaces are being used."""
  #TODO: Use get_default_route() to determine correct interface, and directly
  #      query its IP instead of kludge of making a dummy connection.
  #      In the end, this is fundamentally not 100% correct, because packets to different public
  #      IP's can be routed through different interfaces, depending on the local routing rules.
  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  sock.connect(('8.8.8.8', 53))
  ip = sock.getsockname()[0]
  sock.close()
  return ip
