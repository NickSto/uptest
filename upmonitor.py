#!/usr/bin/env python
#TODO: When your packets are all being dropped, but you have an interface that's
#      "connected" (think a wifi router with no internet connection), ping
#      doesn't "obey" the -W timeout, getting stuck in a DNS lookup.
#      Seems the only way to resolve this situation is to do the DNS yourself
#      and give ping an actual ip address.
#TODO: When using curl, show a third status: "!" when page is intercepted.
#TODO: Try using httplib directly instead of curl
#TODO: Make curl look for an expected response, to catch an intercepted
#      connection at a wifi access point.
#TODO: Maybe an algorithm to automatically switch to curl if there's a streak of
#      failed pings (so no manual intervention is needed)
from __future__ import division
import re
import os
import sys
import copy
import time
import signal
import argparse
import subprocess
import ConfigParser
import distutils.spawn

OPT_DEFAULTS = {'server':'google.com', 'history_length':5, 'frequency':5,
  'timeout':2, 'method':'ping'}
OPT_TYPES = {'server':str, 'history_length':int, 'frequency':int, 'timeout':int,
  'method':str, 'logfile':os.path.abspath, 'data_dir':os.path.abspath}
# USAGE = "%(prog)s [options]"
DESCRIPTION = """Track and summarize the recent history of connectivity by
pinging an external server. Can print a textual summary figure to stdout or to
a file, which can be read and displayed by utilities like indicator-sysmonitor.
This allows visual monitoring of real, current connectivity. The status display
looks something like "[*oo**]", showing the results of the most recent five
pings (newest on the right). *'s indicate successful pings and o's are dropped
pings. All command-line options can be changed without interrupting the running
process by editing upmonitor.cfg. Any invalid settings will be ignored, however.
"""
EPILOG = """"""

DATA_DIRNAME = '.local/share/nbsdata'
SILENCE_FILENAME = 'SILENCE'
HISTORY_FILENAME = 'uphistory.txt'
STATUS_FILENAME = 'upstatus.txt'
CONFIG_FILENAME = 'upmonitor.cfg'
SHUTDOWN_STATUS = '[OFFLINE]'
IP_ROUTE_REGEX = r'^(?:\d{1,3}\.){3}\d{1,3}\s+via\s+(?:\d{1,3}\.){3}\d{1,3}\s+dev\s+(\S+)\s+src\s+(?:\d{1,3}\.){3}\d{1,3}'

def main():

  parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EPILOG)
  parser.set_defaults(**OPT_DEFAULTS)
  OPT_TYPES['stdout'] = tobool

  parser.add_argument('-s', '--server',
    help="""The server to ping. Default: %(default)s""")
  parser.add_argument('-o', '--stdout', action='store_true',
    help="""Print status summary to stdout instead of a file.""")
  parser.add_argument('-f', '--frequency', type=OPT_TYPES['frequency'],
    help="""How frequently to test the connection. Give the interval time in
seconds. Default: %(default)s""")
  parser.add_argument('-l', '--history-length', metavar='LENGTH',
    type=OPT_TYPES['history_length'],
    help="""The number of previous ping tests to keep track of and display.
Default: %(default)s""")
  parser.add_argument('-c', '--curl', dest='method', action='store_const',
    const='curl',
    help="""Use curl instead of ping as the connection test.""")
  parser.add_argument('-t', '--timeout', type=OPT_TYPES['timeout'],
    help="""Seconds to wait for a response to each ping. Cannot be greater than 
"frequency". Default: %(default)s""")
  parser.add_argument('-L', '--logfile', type=OPT_TYPES['logfile'],
    help="""Give a file to log ping history to. Will record the ping latency,
the time, and if possible, the wifi SSID and MAC address (using the "iwconfig"
command). These will be in 4 tab-delimited columns, one line per ping. This file
can be tracked in real-time with upview.py. N.B.: If you aren't connected to
wifi (or if your traffic isn't using wifi), the SSID and MAC address fields will
be empty (but present).""")
  parser.add_argument('-d', '--data-dir', metavar='DIRNAME',
    type=OPT_TYPES['data_dir'],
    help='The directory where data will be stored. History data will be kept '
      'in DIRNAME/'+HISTORY_FILENAME+', the status summary will be in '
      'DIRNAME/'+STATUS_FILENAME+', and configuration settings will be written '
      'to DIRNAME/'+CONFIG_FILENAME+'. Default: a directory named '+DATA_DIRNAME
      +' in the user\'s home directory.')

  args = parser.parse_args()
  check_config(args)

  # determine file paths
  home_dir = os.path.expanduser('~')
  silence_file = os.path.join(home_dir, DATA_DIRNAME, SILENCE_FILENAME)
  (history_file, status_file, config_file) = make_paths(args.data_dir)

  # write settings to config file
  config = ConfigParser.RawConfigParser()
  set_config_args(config, args)
  write_config(config, config_file)

  # attach signal handler to write special status on shutdown or exception
  def invalidate_status():
    with open(status_file, 'w') as filehandle:
      filehandle.write(SHUTDOWN_STATUS)
  def invalidate_and_exit(*args):
    invalidate_status()
    sys.exit()
  # catch system signals
  for signame in ['SIGINT', 'SIGHUP', 'SIGTERM', 'SIGQUIT']:
    sig = getattr(signal, signame)
    signal.signal(sig, invalidate_and_exit)
  # catch exceptions
  def invalidate_and_reraise(type_, value, traceback):
    invalidate_status()
    sys.__excepthook__(type_, value, traceback)
  sys.excepthook = invalidate_and_reraise

  # main loop
  now = int(time.time())
  target = now + args.frequency
  while True:
    if os.path.isfile(silence_file):
      invalidate_status()
      target = sleep(target, args.frequency)
      continue

    # read in config file and update args with new settings
    old_args = copy.deepcopy(args)
    try:
      config = ConfigParser.RawConfigParser()
      config.read(config_file)
      read_config_args(config, args)
      check_config(args, old_args)
      if config.has_option('meta', 'die'):
        invalidate_and_exit()
    except ConfigParser.Error:
      # keeping the process up is secondary to changing settings on the fly
      pass
    (history_file, status_file, config_file) = make_paths(args.data_dir)
    # update config file with new settings
    try:
      config = ConfigParser.RawConfigParser()
      set_config_args(config, args)
      write_config(config, config_file)
    except ConfigParser.Error:
      pass

    # read in history from file
    history = []
    if os.path.isfile(history_file):
      history = get_history(history_file, args.history_length)
    elif os.path.exists(history_file):
      fail('Error: history file "'+history_file+'" is a non-file.')
    # remove outdated pings
    now = int(time.time())
    prune_history(history, args.history_length - 1, args.frequency, now=now)

    # ping and get status
    result = ping(args.server, method=args.method, timeout=args.timeout)
    if result:
      status = 'up'
    else:
      status = 'down'
    history.append((now, status))

    # log result
    if args.logfile:
      log(args.logfile, result, now, server=args.server)

    # write new history back to file
    if os.path.exists(history_file) and not os.path.isfile(history_file):
      fail('Error: history file "'+history_file+'" is a non-file.')
    write_history(history_file, history)

    # write status stat to file (or stdout)
    if os.path.exists(status_file) and not os.path.isfile(status_file):
      fail('Error: status file "'+status_file+'" is a non-file.')
    status_str = status_format(history, args.history_length)
    if args.stdout:
      print status_str
    else:
      with open(status_file, 'w') as filehandle:
        filehandle.write(status_str.encode('utf8'))

    target = sleep(target, args.frequency)


def make_paths(data_dir):
  """Create the the data_dir directory and return full paths to its files.
  Give args.data_dir as the argument. If args.data_dir is false, the data_dir
  will be DATA_DIRNAME in the user's home directory.
  Returns (history_file, status_file, config_file)."""
  home_dir = os.path.expanduser('~')
  if not data_dir:
    data_dir = os.path.join(home_dir, DATA_DIRNAME)
  if not os.path.exists(data_dir):
    os.makedirs(data_dir)
  history_file = os.path.join(data_dir, HISTORY_FILENAME)
  status_file = os.path.join(data_dir, STATUS_FILENAME)
  config_file = os.path.join(data_dir, CONFIG_FILENAME)
  return (history_file, status_file, config_file)


def set_config_args(config, args):
  """Write settings (argparse args) to the 'args' section of the config file."""
  config.add_section('args')
  for arg in vars(args):
    value = getattr(args, arg)
    if value is not None:
      config.set('args', arg, getattr(args, arg))


def write_config(config, config_file):
  """Set the config sections that aren't 'args' and write to file."""
  config.add_section('meta')
  config.set('meta', 'pid', os.getpid())
  with open(config_file, 'wb') as filehandle:
    config.write(filehandle)


def read_config_args(config, args):
  """Read all arguments from config file and update args attributes with them.
  If the [meta] "die" option is present, set args.die to True.
  If there is any error reading the file, change nothing and return."""
  for arg in config.options('args'):
    # if the option exists, cast it to the proper type and set as args attr
    if config.has_option('args', arg):
      cast = OPT_TYPES[arg]
      try:
        setattr(args, arg, cast(config.get('args', arg)))
      except ValueError:
        pass


def check_config(args, old_args=None):
  """Check certain arguments for validity.
  If old_args is not given, an AssertionError will be raised on invalid
  arguments. If old_args is given, invalid arguments will be replaced with their
  previous values. This is to be used when the process cannot be interrupted."""
  if args.timeout > args.frequency:
    if old_args is None:
      raise AssertionError('Sleep time must be longer than ping timeout.')
    else:
      args.timeout = old_args.timeout
      args.frequency = old_args.frequency
  if args.method not in ['ping', 'curl']:
    if old_args is None:
      raise AssertionError('Ping method must be one of "ping" or "curl".')
    else:
      args.method = old_args.method
  if args.data_dir and not os.path.isdir(args.data_dir):
    if old_args is None:
      raise AssertionError('Given data directory does not exist.')
    else:
      args.data_dir = old_args.data_dir
  if args.logfile and not os.path.exists(os.path.dirname(args.logfile)):
    if old_args is None:
      raise AssertionError('Given log file is an invalid pathname.')
    else:
      args.logfile = old_args.logfile


def get_history(history_file, history_length):
  """Parse history file, return it in a list of (timestamp, status) tuples.
  "timestamp" is an int and "status" is either "up" or "down". Lines which don't
  conform to "timestamp\tstatus" are skipped. If the file does not exist or is
  empty, an empty list is returned. The list is in the same order as the lines
  in the file."""
  history = []
  with open(history_file, 'rU') as file_handle:
    for line in file_handle:
      fields = line.strip().split('\t')
      try:
        history.append((int(fields[0]), fields[1]))
      except (ValueError, IndexError):
        continue
  return history


def prune_history(history, past_points, frequency, now=None):
  """Remove history points older than a cutoff age.
  The cutoff is calculated to ideally retain "past_points" points, assuming
  pings have consistently been sent every "frequency" seconds. See get_history()
  for the format of the "history" data structure."""
  if now is None:
    now = int(time.time())
  cutoff = now - (frequency * past_points) - 2 # 2 second fudge factor
  history[:] = [line for line in history if line[0] >= cutoff]
  return history


def ping(server, method='ping', timeout=2):
  """Ping "server", and return the ping time in milliseconds.
  If the ping fails, returns 0.
  If the method is "curl", the returned time is the "time_connect" variable of
  curl's "-w" option (multiplied by 1000 to get ms). In practice the time is
  very similar to a simple ping."""
  devnull = open(os.devnull, 'w')
  assert method in ['ping', 'curl'], 'Error: Invalid ping method'
  if method == 'ping':
    command = ['ping', '-n', '-c', '1', '-W', str(timeout), server]
  elif method == 'curl':
    command = ['curl', '-s', '--output', '/dev/null', '--write-out',
      r'%{time_connect}', '--connect-timeout', str(timeout), server]
  # call command
  try:
    output = subprocess.check_output(command, stderr=devnull)
    exit_status = 0
  except subprocess.CalledProcessError as cpe:
    output = cpe.output
    exit_status = cpe.returncode
  except OSError:
    output = ''
    exit_status = 1
  finally:
    devnull.close()
  # parse output or return 0 on error
  if exit_status == 0:
    if method == 'ping':
      return parse_ping(output)
    elif method == 'curl':
      return parse_curl(output)
  else:
    return 0.0


def parse_ping(ping_str):
  """Parse out the ms of the ping from the output of `ping -n -c 1`"""
  ping_pattern = r' bytes from .* time=([\d.]+) ?ms'
  for line in ping_str.splitlines():
    match = re.search(ping_pattern, line)
    if match:
      try:
        return float(match.group(1))
      except ValueError:
        return 0.0
  return 0.0


def parse_curl(curl_str):
  """Parse the output of curl into a number of milliseconds (float)."""
  try:
    return 1000*float(curl_str)
  except ValueError:
    return 0.0


def write_history(history_file, history):
  """Write the current history data structure to the history file.
  See get_history() for the format of the "history" data structure."""
  with open(history_file, 'w') as filehandle:
    for line in history:
      filehandle.write("{}\t{}\n".format(line[0], line[1]))


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


def get_default_interface(domain='google.com'):
  """Determine the default networking interface in use at the moment by using
  the 'ip route get' command for a known external IP.
  Returns None on error."""
  # Other IP's to check: 127.1.2.3 (local), 0.5.4.3 (unroutable)
  EXTERNAL_IP_DEFAULT = '74.125.228.6'
  interface = None
  # check if 'ip' command is available
  if not distutils.spawn.find_executable('ip'):
    return None
  # call 'ip' command
  output = get_ip_route(EXTERNAL_IP_DEFAULT)
  # output is None if there's an error in the 'ip' command or its output
  if output is None:
    sys.stderr.write('External ip '+EXTERNAL_IP_DEFAULT+' not routable. '
      'Doing extra DNS query to find a new one.\n')
    external_ip = dig_ip(domain)
    if external_ip is None:
      return None
    output = get_ip_route(external_ip)
    if output is None:
      return None
  match = re.search(IP_ROUTE_REGEX, output)
  if match:
    interface = match.group(1)
  return interface


def get_ip_route(ip):
  """Do 'ip route get [ip]' command, returning None on error or if the output
  is not expected (doesn't match IP_ROUTE_REGEX)."""
  devnull = open(os.devnull, 'w')
  try:
    output = subprocess.check_output(['ip', 'route', 'get', ip], stderr=devnull)
  except (OSError, subprocess.CalledProcessError):
    return None
  finally:
    devnull.close()
  if not re.search(IP_ROUTE_REGEX, output):
    return None
  return output


def dig_ip(domain):
  """Use 'dig' command to get the first IP returned in a DNS query for 'domain'.
  On error, or no result, returns None."""
  if not distutils.spawn.find_executable('ip'):
    return None
  devnull = open(os.devnull, 'w')
  try:
    output = subprocess.check_output(['dig', '+short', '+time=1', '+tries=2', domain], stderr=devnull)
  except (OSError, subprocess.CalledProcessError):
    return None
  finally:
    devnull.close()
  for line in output.splitlines():
    return line.strip()
  return None


#TODO: If you aren't connected to wifi, record the MAC address of whatever your
#      default interface is connected to.
def log(logfile, result, now, server='google.com'):
  """Log the result of the ping to the given log file.
  Writes the ping milliseconds ("result"), current timestamp ("now"), wifi ssid,
  and wifi mac address as separate columns in a line appended to the file.
  If you're not connected to wifi, or if it isn't your default interface, the
  ssid and mac columns will be empty."""
  (wifi_interface, ssid, mac) = get_wifi_info()
  active_interface = get_default_interface(server)
  if wifi_interface != active_interface:
    ssid = ''
    mac = ''
  if ssid is None:
    ssid = ''
  if mac is None:
    mac = ''
  with open(logfile, 'a') as filehandle:
    if result == 0 or result >= 100:
      filehandle.write("{:d}\t{:d}\t{}\t{}\n".format(int(result), now, ssid, mac))
    else:
      filehandle.write("{:.1f}\t{:d}\t{}\t{}\n".format(result, now, ssid, mac))


def status_format(history, history_length):
  """Create a human-readable status display string out of the recent history."""
  status_str = u'['
  for line in history:
    if line[1] == 'up':
      status_str += u' \u2022'
      # status_str += u'\u26AB' # medium bullet
    else:
      # add a space to left of a run of o's, for aesthetics
      if status_str[-1] == u'[' or status_str[-1] == u'\u2022':
        status_str += u' '
      status_str += u'o'
  status_str += u' ]'
  return status_str


def sleep(target, delay=5, precision=0.1):
  """Sleep until "target" (unix timestamp), and return a new target "delay"
  seconds later. It does this by sleeping in increments of "precision" seconds.
  To accommodate system suspend and other pauses in execution, if the current
  time is more than one step (increment of "delay") beyond "target", then the
  target will be raised by a multiple of delay until it's one step below the
  current time.
  """
  if precision <= 0:
    raise ValueError('Sleep precision must be greater than zero.')
  now = int(time.time())
  # If now already past the target, increase target in multiples of delay until
  # it's just under now.
  if now > target:
    target += delay * ((now - target) // delay)
  while now < target:
    time.sleep(precision)
    now = int(time.time())
  return target + delay


def tobool(bool_str):
  """Parse a bool literal from a str."""
  if bool_str == 'True':
    return True
  elif bool_str == 'False':
    return False
  else:
    raise ValueError('invalid boolean literal: '+bool_str)


def fail(message):
  sys.stderr.write(message+"\n")
  sys.exit(1)


if __name__ == '__main__':
  main()
