#!/usr/bin/env python
#TODO: When your packets are all being dropped, but you have an interface that's
#      "connected" (think a wifi router with no internet connection), ping
#      doesn't "obey" the -W timeout, getting stuck in a DNS lookup.
#      Seems the only way to resolve this situation is to do the DNS yourself
#      and give ping an actual ip address.
#TODO: When using curl, show a third status: "!" when page is intercepted.
#      Use http://www.gstatic.com/generate_204 for this by default.
#      See Google Chrome's methods for detecting interception:
#      http://www.chromium.org/chromium-os/chromiumos-design-docs/network-portal-detection
#TODO: Try using httplib directly instead of curl (or requests module?)
#TODO: Maybe an algorithm to automatically switch to curl if there's a streak of
#      failed pings (so no manual intervention is needed)
from __future__ import division
import re
import os
import sys
import copy
import time
import signal
import socket
import httplib
import numbers
import argparse
import subprocess
import ConfigParser
import ipwraplib

OPT_DEFAULTS = {'server':'google.com', 'history_length':5, 'frequency':5,
  'timeout':2, 'method':'ping'}
#TODO: Just put these next to each argument definition in main().
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

def main():

  parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EPILOG)
  parser.set_defaults(**OPT_DEFAULTS)
  OPT_TYPES['stdout'] = tobool

  parser.add_argument('-s', '--server',
    help='The server to ping. Default: %(default)s')
  parser.add_argument('-o', '--stdout', action='store_true',
    help='Print status summary to stdout instead of a file.')
  parser.add_argument('-f', '--frequency', type=OPT_TYPES['frequency'],
    help='How frequently to test the connection. Give the interval time in '
      'seconds. Default: %(default)s')
  parser.add_argument('-l', '--history-length', metavar='LENGTH',
    type=OPT_TYPES['history_length'],
    help='The number of previous ping tests to keep track of and display. '
     'Default: %(default)s')
  parser.add_argument('-m', '--method', choices=('ping', 'curl', 'httplib'),
    help='Select method to use for determining connection status, latency, and '
      '(in the case of httplib) connection interception. Default: %(default)s')
  parser.add_argument('-t', '--timeout', type=OPT_TYPES['timeout'],
    help='Seconds to wait for a response to each ping. Cannot be greater than '
      '"frequency". Default: %(default)s')
  parser.add_argument('-L', '--logfile', type=OPT_TYPES['logfile'],
    help='Give a file to log ping history to. Will record the ping latency, '
      'the time, and if possible, the wifi SSID and MAC address (using the '
      '"iwconfig" command). These will be in 4 tab-delimited columns, one line '
      'per ping. This file can be tracked in real-time with upview.py. N.B.: '
      'If you aren\'t connected to wifi, the SSID and MAC address fields will '
      'be empty (but present). If you\'re connected, but the pings aren\'t '
      'going through the wifi connection, the SSID will be empty but the MAC '
      'will be the address of whatever device you\'re actually using (like '
      'an Ethernet switch).')
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
  #TODO: Check if config already exists, and if an instance is already running.
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
      # keeping the process up takes precedence over changing settings on the fly
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
    if args.method == 'httplib':
      (result, expected) = ping_and_check(timeout=args.timeout)
    else:
      result = ping(args.server, method=args.method, timeout=args.timeout)
      expected = True
    if result:
      if expected:
        status = 'up'
      else:
        status = 'intercepted'
    else:
      status = 'down'
    history.append((now, status))

    # log result
    if args.logfile:
      log(args.logfile, result, now, method=args.method)

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
  if args.method not in ('ping', 'curl', 'httplib'):
    if old_args is None:
      raise AssertionError('Ping method must be one of "ping", "curl", or "httplib".')
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
  "timestamp" is an int and "status" is "up", "down", or "intercepted". Lines
  which don't conform to "timestamp\tstatus" are skipped. If the file does not
  exist or is empty, an empty list is returned. The list is in the same order
  as the lines in the file."""
  history = []
  with open(history_file, 'rU') as file_handle:
    for line in file_handle:
      try:
        (timestamp, status) = line.strip().split('\t')
      except ValueError:
        continue
      try:
        history.append((int(timestamp), status))
      except ValueError:
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


def ping_and_check(timeout=2):
  """Return (float, bool): latency in ms and whether the response was as expected."""
  #TODO: Maybe go back to http://www.nsto.co/misc/access.txt
  #      http://www.gstatic.com/generate_204 sometimes doesn't work.
  #      I.e. on attwifi
  conex = httplib.HTTPConnection('www.gstatic.com', timeout=timeout)
  try:
    conex.request('GET', '/generate_204')
  except (socket.error, socket.gaierror):
    return (0.0, None)
  #TODO: Check what measurement point gets the most accurate time.
  #      Maybe break .request() into the four methods described here:
  #      https://docs.python.org/2/library/httplib.html#httplib.HTTPConnection.putrequest
  before = time.time()
  try:
    response = conex.getresponse()
  except socket.timeout:
    return (0.0, None)
  after = time.time()
  elapsed = round(1000 * (after - before), 1)
  if response.status == 204 and response.read(1024) == '':
    expected = True
  else:
    expected = False
  return (elapsed, expected)


def write_history(history_file, history):
  """Write the current history data structure to the history file.
  See get_history() for the format of the "history" data structure."""
  with open(history_file, 'w') as filehandle:
    for (timestamp, status) in history:
      filehandle.write("{}\t{}\n".format(timestamp, status))


def log(logfile, result, now, method=None):
  """Log the result of the ping to the given log file.
  Writes the ping milliseconds ("result"), current timestamp ("now"), wifi SSID,
  and wifi MAC address as separate columns in a line appended to the file.
  If you're not connected to wifi, or if it isn't your default interface, the
  SSID column will be empty and the MAC address will be of whatever device
  your default interface is attached to (the default route)."""
  (wifi_interface, ssid, mac) = ipwraplib.get_wifi_info()
  (active_interface, default_route) = ipwraplib.get_default_route()
  if wifi_interface != active_interface:
    ssid = ''
    mac = ipwraplib.get_mac_from_ip(default_route)
  columns = [result, now, ssid, mac, method]
  line = "\t".join(map(format_value, columns))+'\n'
  with open(logfile, 'a') as filehandle:
    filehandle.write(line)


def format_value(raw):
  """Format a data value for entry into the log file.
  Values are converted to strings, except None, which becomes ''."""
  value = raw
  if isinstance(value, numbers.Number) and (value == 0 or value >= 100):
    value = int(value)
  if value is None:
    return ''
  else:
    return str(value)


def status_format(history, history_length):
  """Create a human-readable status display string out of the recent history."""
  status_str = u'['
  for (timestamp, status) in history:
    if status == 'up':
      status_str += u' \u2022'
      # status_str += u'\u26AB' # medium bullet
    elif status == 'intercepted':
      status_str += u' !'
    else:
      # add a space to left of a run of o's, for aesthetics
      if status_str[-1] == u'[' or status_str[-1] == u'\u2022':
        status_str += u' '
      if status == 'down':
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
