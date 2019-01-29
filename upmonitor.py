#!/usr/bin/env python
#TODO: Note interception in log file and show in upview.py. Right now it's shown as "0", the same as
#      a dropped ping (technically true, but it could be more specific).
#TODO: Try requests library instead of httplib (can be packaged with the code).
#TODO: Maybe an algorithm to automatically switch to curl if there's a streak of failed pings (so no
#      manual intervention is needed).
#TODO: When your packets are all being dropped, but you have an interface that's "connected" (think
#      a wifi router with no internet connection), ping doesn't "obey" the -W timeout, getting stuck
#      in a DNS lookup. Seems the only way to resolve this situation is to do the DNS yourself and
#      give ping an actual ip address.
#TODO: Dealing with hotspots caching responses.
#      The Cache-Control/Pragma headers might be enough to take care of hotspot caches.
#      If not, HTTPS would be ideal, but it introduces additional round trips that aren't possible
#      to disintangle in Python. Instead, I could run a server which I could send a nonce to, then
#      have it manipulate it in a specific way and return it. Not sure whether to actually encrypt
#      it with a secret key, which introduces the complexity of key management. In reality, no one's
#      going to be trying to game this system. So instead I could just use a simple manipulation
#      (even nonce+1 would work, honestly).
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import
import re
import os
import sys
import copy
import time
import errno
import signal
import socket
import httplib
import numbers
import argparse
import subprocess
import ConfigParser
import ipwraplib
try:
  import dns.resolver
  import dns.exception
except ImportError:
  pass


DATA_DIR_DEFAULT = '.local/share/nbsdata'
SILENCE_FILENAME = 'SILENCE'
HISTORY_FILENAME = 'uphistory.txt'
STATUS_FILENAME = 'upstatus.txt'
CONFIG_FILENAME = 'upmonitor.cfg'
SHUTDOWN_STATUS = '[OFFLINE]'
HTTP_HEADERS = {'Cache-Control':'no-cache', 'Pragma':'no-cache'}
DETECTORS = {
  'google': {'server':'www.gstatic.com', 'path':'/generate_204', 'status':204, 'body':''},
  'mozilla': {'server':'detectportal.firefox.com', 'path':'/success.txt', 'status':200,
              'body':'success\n'}
}
DETECTOR_ALIASES = {'google.com':'google', 'gstatic.com':'google', 'www.gstatic.com':'google',
                    'firefox':'mozilla', 'firefox.com':'mozilla', 'detectportal.firefox.com':'mozilla'}

OPT_DEFAULTS = {'server':'google.com', 'history_length':5, 'frequency':5, 'timeout':2,
                'method':'ping'}
DESCRIPTION = """Track and summarize the recent history of connectivity by pinging an external
server. Can print a textual summary figure to stdout or to a file, which can be read and displayed
by utilities like indicator-sysmonitor. This allows visual monitoring of real, current connectivity.
The status display looks something like "[*oo**]", showing the results of the most recent five pings
(newest on the right). *'s indicate successful pings and o's are dropped pings. All command-line
options can be changed without interrupting the running process by editing
~/"""+DATA_DIR_DEFAULT+'/'+CONFIG_FILENAME+""". Any invalid settings will be ignored."""
EPILOG = """This is meant as a pragmatic script to give you a quick answer to the question "Am I
connected?". This can best be answered by simply trying to connect to a server outside your network.
Using this simple approach means it avoids the intricacies of determining whether each link between
you and the outside world is functioning: network stack, router, modem, ISP, etc. But it also means
its answer is only "yes" or "no". Diagnosing a "no" requires more sophisticated tools. This
philosophy is also why httplib is the recommended method. It simulates as closely as possible the
normal use of a network connection: making HTTP requests (*without* it being intercepted en route).
"""


def make_parser():
  parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EPILOG)
  parser.set_defaults(**OPT_DEFAULTS)
  opts = {}
  opts['server'] = parser.add_argument('-s', '--server',
    help='The server to ping. If --method is "httplib", then give the name of one of the '
         'following captive portal detectors: '+describe_detectors(DETECTORS)+'.')
  opts['stdout'] = parser.add_argument('-o', '--stdout', action='store_true',
    help='Print status summary to stdout instead of a file.')
  opts['frequency'] = parser.add_argument('-f', '--frequency', type=int,
    help='How frequently to test the connection. Give the interval time in seconds. Default: '
         '%(default)s')
  opts['history_length'] = parser.add_argument('-l', '--history-length', metavar='LENGTH', type=int,
    help='The number of previous ping tests to keep track of and display. Default: %(default)s')
  opts['method'] = parser.add_argument('-m', '--method', choices=('ping', 'curl', 'httplib'),
    help='Select method to use for determining connection information. "ping" uses the ping '
         'command, "curl" uses the curl command to send an HTTP GET request to the server\'s root '
         '("/") path, and httplib makes an HTTP GET request to the selected captive portal '
         'detector and checks the result against the expected result. If the request succeeded but '
         'is not what was expected, this counts as an offline result, and this interception is '
         'represented in the status display with a "!". Default: %(default)s')
  opts['timeout'] = parser.add_argument('-t', '--timeout', type=int,
    help='Seconds to wait for a response to each ping. Cannot be greater than "frequency". '
         'Default: %(default)s')
  opts['logfile'] = parser.add_argument('-L', '--logfile', type=os.path.abspath,
    help='Give a file to log ping history to. Will record the ping latency, the time, and if '
         'possible, the wifi SSID and MAC address (using the iwconfig" command). These will be in '
         '4 tab-delimited columns, one line per ping. This file can be tracked in real-time with '
         'upview.py. N.B.: If you aren\'t connected to wifi, the SSID and MAC address fields will '
         'be empty (but present). If you\'re connected, but the pings aren\'t going through the '
         'wifi connection, the SSID will be empty but the MAC will be the address of whatever '
         'device you\'re actually using (like an Ethernet switch).')
  opts['data_dir'] = parser.add_argument('-D', '--data-dir', metavar='DIRNAME', type=os.path.abspath,
    help='The directory where data will be stored. History data will be kept in DIRNAME/'
         +HISTORY_FILENAME+', the status display will be in DIRNAME/'+STATUS_FILENAME+', and '
         'configuration settings will be written to DIRNAME/'+CONFIG_FILENAME+'. Default: ~/'
         +DATA_DIR_DEFAULT)
  return (parser, opts)


def main():
  (parser, opts) = make_parser()

  args = parser.parse_args()
  check_config(args)

  # Determine file paths.
  home_dir = os.path.expanduser('~')
  silence_file = os.path.join(home_dir, DATA_DIR_DEFAULT, SILENCE_FILENAME)
  (history_file, status_file, config_file) = make_paths(args.data_dir)

  # Exit if an instance is already running.
  if is_running(config_file):
    pid = str(is_running(config_file))
    sys.stderr.write('Error: an instance is already running at pid '+pid+'.\n')
    sys.exit(1)

  # Write settings to config file.
  config = ConfigParser.RawConfigParser()
  write_config(config_file, config, args)

  # Attach signal handler to write special status on shutdown or exception.
  # Define here to have access to have access to the status filename.
  def invalidate_status():
    with open(status_file, 'w') as filehandle:
      filehandle.write(SHUTDOWN_STATUS)
  def invalidate_and_exit(*args):
    invalidate_status()
    os.remove(config_file)
    sys.exit()
  # Catch system signals.
  for signame in ['SIGINT', 'SIGHUP', 'SIGTERM', 'SIGQUIT']:
    sig = getattr(signal, signame)
    signal.signal(sig, invalidate_and_exit)
  # Catch exceptions.
  def invalidate_and_reraise(type_, value, traceback):
    invalidate_status()
    sys.__excepthook__(type_, value, traceback)
  sys.excepthook = invalidate_and_reraise

  # What version of ping?
  ping_ver = get_ping_version()

  # Main loop.
  now = int(time.time())
  target = now + args.frequency
  while True:
    if os.path.isfile(silence_file):
      invalidate_status()
      target = sleep(target, args.frequency)
      continue

    # Read in config file and update args with new settings.
    old_args = copy.deepcopy(args)
    changed = False
    try:
      config = ConfigParser.RawConfigParser()
      config.read(config_file)
      changed = read_config_args(config, args, opts)
      check_config(args, old_args)
      if config.has_option('meta', 'die') and config.get('meta', 'die').lower() == 'true':
        invalidate_and_exit()
    except ConfigParser.Error:
      # Keeping the process up takes precedence over changing settings on the fly.
      pass
    (history_file, status_file, config_file) = make_paths(args.data_dir)
    # Update config file with new settings.
    if changed:
      try:
        config = ConfigParser.RawConfigParser()
        write_config(config_file, config, args)
      except ConfigParser.Error:
        pass

    # Read in history from file.
    history = []
    if os.path.isfile(history_file):
      history = get_history(history_file, args.history_length)
    elif os.path.exists(history_file):
      fail('Error: history file "'+history_file+'" is a non-file.')
    # Remove outdated pings.
    now = int(time.time())
    prune_history(history, args.history_length - 1, args.frequency, now=now)

    # Ping and get status.
    if args.method == 'httplib':
      server = DETECTOR_ALIASES.get(args.server, args.server)
      detector = DETECTORS[server]
      (result, intercepted) = ping_and_check(timeout=args.timeout, **detector)
    else:
      result = ping(args.server, method=args.method, timeout=args.timeout, ping_ver=ping_ver)
      intercepted = None
    if result:
      if intercepted is True:
        status = 'intercepted'
      else:
        status = 'up'
    else:
      status = 'down'
    history.append((now, status))

    # Log result.
    if args.logfile:
      log(args.logfile, result, now, intercepted=intercepted, method=args.method)

    # Write new history back to file.
    if os.path.exists(history_file) and not os.path.isfile(history_file):
      fail('Error: history file "'+history_file+'" is a non-file.')
    write_history(history_file, history)

    # Write status stat to file (or stdout).
    if os.path.exists(status_file) and not os.path.isfile(status_file):
      fail('Error: status file "'+status_file+'" is a non-file.')
    status_str = status_format(history, args.history_length)
    if args.stdout:
      print(status_str)
    else:
      with open(status_file, 'w') as filehandle:
        filehandle.write(status_str.encode('utf8'))

    target = sleep(target, args.frequency)


def make_paths(data_dir):
  """Create the the data_dir directory and return full paths to its files.
  Give args.data_dir as the argument. If args.data_dir is false, the data_dir
  will be DATA_DIR_DEFAULT in the user's home directory.
  Returns (history_file, status_file, config_file)."""
  home_dir = os.path.expanduser('~')
  if not data_dir:
    data_dir = os.path.join(home_dir, DATA_DIR_DEFAULT)
  if not os.path.exists(data_dir):
    os.makedirs(data_dir)
  history_file = os.path.join(data_dir, HISTORY_FILENAME)
  status_file = os.path.join(data_dir, STATUS_FILENAME)
  config_file = os.path.join(data_dir, CONFIG_FILENAME)
  return (history_file, status_file, config_file)


def is_running(config_file):
  """Determine if an instance is already running by reading its pid from a
  config file.
  Returns the pid (an int) if the process is running, False if it isn't, and
  None if it can't tell."""
  config = ConfigParser.RawConfigParser()
  config.read(config_file)
  if config.has_option('meta', 'pid'):
    try:
      pid = int(config.get('meta', 'pid'))
    except ValueError:
      return None
    # Check if the process is running: try sending signal 0 to the process.
    # If it's not running, an OSError will be raised with errno ESRCH (no such process).
    try:
      os.kill(pid, 0)
      #TODO: Check if the process is actually an upmonitor.py one.
      #      Try psutil package or ps command, if either is available.
      #      Or maybe just send a special signal to it, and have it react in a detectable way.
      return pid
    except OSError as ose:
      if ose.errno == errno.ESRCH:
        return False
      else:
        return None
  else:
    return None


def write_config(config_file, config, args):
  """Write settings to config_file.
  All values in "args" will be written to the [args] section."""
  # [meta] section
  config.add_section('meta')
  config.set('meta', 'pid', os.getpid())
  config.set('meta', 'die', False)
  # [args] section
  config.add_section('args')
  for arg in vars(args):
    value = getattr(args, arg)
    if value is not None:
      config.set('args', arg, getattr(args, arg))
  # Write to file.
  with open(config_file, 'wb') as filehandle:
    config.write(filehandle)


def read_config_args(config, args, opts):
  """Read all arguments from config file and update args attributes with them.
  If there is any error reading the file, change nothing and return.
  Return True if there are changes to any argument value."""
  changed = False
  for arg in config.options('args'):
    # If the option exists, cast it to the proper type and set as args attr.
    if config.has_option('args', arg):
      # Get a casting function to cast a string to the argument type.
      if opts[arg].type is not None:
        cast = opts[arg].type
      elif opts[arg].default is not None:
        cast = type(opts[arg].default)
      else:
        cast = str
      if cast is bool:
        cast = tobool
      # Get the config value and cast it.
      try:
        new_value = cast(config.get('args', arg))
      except ValueError:
        continue
      try:
        if new_value != getattr(args, arg):
          setattr(args, arg, new_value)
          changed = True
      except AttributeError:
        continue
  return changed


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
  if args.method == 'httplib' and args.server not in DETECTOR_ALIASES and args.server not in DETECTORS:
    if old_args is None:
      raise AssertionError('Server not in list of captive portal detectors.')
    else:
      args.method = old_args.method
      args.server = old_args.server


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
  cutoff = now - (frequency * past_points) - 2  # 2 second fudge factor
  history[:] = [line for line in history if line[0] >= cutoff]
  return history


def ping(server, method='ping', timeout=2, ping_ver=None):
  """Ping "server", and return the ping time in milliseconds.
  If the ping fails, returns 0.
  If the method is "curl", the returned time is the "time_connect" variable of
  curl's "-w" option (multiplied by 1000 to get ms). In practice the time is
  very similar to a simple ping."""
  devnull = open(os.devnull, 'w')
  # Build command.
  assert method in ['ping', 'curl'], 'Error: Invalid ping method'
  if method == 'ping':
    # Timeout depends on which version of ping. If it can't be determined, don't set timeout.
    if ping_ver == 'iputils':
      command = ['ping', '-n', '-c', '1', '-w', str(timeout), server]
    elif ping_ver == 'bsd':
      command = ['ping', '-n', '-c', '1', '-t', str(timeout), server]
    else:
      command = ['ping', '-n', '-c', '1', server]
  elif method == 'curl':
    command = ['curl', '-s', '--output', '/dev/null', '--write-out', r'%{time_connect}',
               '--connect-timeout', str(timeout), server]
  # Call command.
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
  # Parse output or return 0.0 on error.
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


def ping_and_check(timeout=2, server='www.gstatic.com', path='/generate_204', status=204, body=''):
  """"Ping" a server with an HTTP GET request, returning the latency and whether
  the response appears to be intercepted (i.e. by a captive portal).
  By default, uses http://www.gstatic.com/generate_204 and assumes interception
  if the response code isn't 204 or the body isn't "". You can customize the
  url and expected response with the respective parameters.
  The latency is determined from the TCP handshake, so it should be a single
  round trip.
  Returns (float, bool): latency in milliseconds and whether the response looks
  intercepted. If no connection can be established, returns (0.0, None). If an
  error is encountered at any point, returns None for the second value."""
  #TODO: Do DNS lookup first, manually, setting timeout:
  #      https://stackoverflow.com/questions/8989457/dnspython-setting-query-timeout-lifetime
  #      Or just use standard library's socket.gethostbyname(), setting timeout using signal.alarm():
  #      https://stackoverflow.com/questions/492519/timeout-on-a-python-function-call/494273#494273
  conex = httplib.HTTPConnection(server, timeout=timeout)
  # .connect() just establishes the TCP connection with a SYN, SYN/ACK, ACK handshake, returning
  # after the final ACK is sent. This is essentially immediately after the SYN/ACK arrives, making
  # it a good measure of a single round trip. The only exception is when a DNS request has to be
  # made first because the IP is no longer in the cache.
  before = time.time()
  try:
    conex.connect()
  except (httplib.HTTPException, socket.error):
    return (0.0, None)
  after = time.time()
  elapsed = round(1000 * (after - before), 1)
  try:
    conex.request('GET', path, None, HTTP_HEADERS)
  except (httplib.HTTPException, socket.error):
    return (elapsed, None)
  try:
    response = conex.getresponse()
  except (httplib.HTTPException, socket.error):
    return (elapsed, None)
  # Is the response as expected?
  # If only an expected status is given (body is None), only that has to match.
  # If a status and body is given, both have to match. This is a little verbose for clarity.
  response_body = response.read(len(body)+1)
  if response.status == status and (body is None or response_body == body):
    expected = True
  else:
    expected = False
  conex.close()
  intercepted = not expected
  return (elapsed, intercepted)


def dns_lookup(domain, timeout=2):
  """Do a DNS lookup with a certain timeout, if possible."""
  # If dns module is installed (and imported).
  if 'dns' in globals():
    return dns_lookup_dns(domain, timeout=timeout)
  else:
    return dns_lookup_socket(domain)


def dns_lookup_dns(domain, timeout=2):
  """Use "dns" module to look up an IP address, returning in a specified amount of time.
  Returns None on timeout or error."""
  resolver = dns.resolver.Resolver()
  resolver.timeout = timeout
  resolver.lifetime = timeout
  try:
    results = resolver.query(domain)
  except dns.exception.DNSException:
    return None
  try:
    # Just pick the first IP address returned.
    return str(results[0])
  except IndexError:
    return None


def dns_lookup_socket(domain):
  """Use socket.gethostbyname() to look up an IP address.
  Returns None on error."""
  try:
    ip = socket.gethostbyname(domain)
  except (socket.timeout, socket.gaierror):
    return None
  return ip


def write_history(history_file, history):
  """Write the current history data structure to the history file.
  See get_history() for the format of the "history" data structure."""
  with open(history_file, 'w') as filehandle:
    for (timestamp, status) in history:
      filehandle.write("{}\t{}\n".format(timestamp, status))


def log(logfile, result, now, intercepted=None, method=None):
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
  if intercepted is True:
    columns = [0, now, ssid, mac, method]
  else:
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
  status_str = ''
  for (timestamp, status) in history:
    if status == 'up':
      # Represent a successful ping with U+2022 (BULLET).
      # Alternative: U+26AB (MEDIUM BULLET).
      # Add spaces between bullets.
      if not status_str or status_str.endswith('\u2022 '):
        status_str += '\u2022 '
      else:
        status_str += ' \u2022 '
    elif status == 'intercepted':
      status_str += '!'
    else:
      if status == 'down':
        # Add a space to left of a run of o's, for aesthetics.
        if not status_str or (status_str[-1] != 'o' and status_str[-1] != ' '):
          status_str += ' o'
        else:
          status_str += 'o'
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
  # If now already past the target, increase target in multiples of delay until it's just under now.
  if now > target:
    target += delay * ((now - target) // delay)
  while now < target:
    time.sleep(precision)
    now = int(time.time())
  return target + delay


def get_ping_version():
  """Try to determine what version of ping is available.
  Currently recognizes the BSD and iputils versions, returning "bsd" and
  "iputils" for them, respectively. For all others, returns the first line of
  the output of "ping -V". On error, returns None."""
  devnull = open(os.devnull, 'w')
  # Call command.
  try:
    output = subprocess.check_output(['ping', '-V'], stderr=devnull)
    exit_status = 0
  except subprocess.CalledProcessError as cpe:
    output = cpe.output
    exit_status = cpe.returncode
  except OSError:
    output = ''
    exit_status = 1
  finally:
    devnull.close()
  # BSD lacks -V option and errors out with exit status 64
  if exit_status == 64 and output == '':
    return 'bsd'
  elif exit_status != 0:
    return None
  # Parse output
  output_lines = output.splitlines()
  if len(output_lines) == 0:
    return None
  if 'iputils' in output_lines[0]:
    return 'iputils'
  else:
    return output_lines[0]


def describe_detectors(detectors):
  detector_strs = []
  for name, detector in detectors.items():
   url = 'http://{server}{path}'.format(**detector)
   detector_strs.append('"{}" ({})'.format(name, url))
  return ', '.join(detector_strs[:-1])+' or '+detector_strs[-1]


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
