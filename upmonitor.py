#!/usr/bin/env python
#TODO: Write some warning like '[?????]' when shutting down by interrupt or
#      SILENCE file, to make sure it's clear that the previous status is no
#      longer accurate.
#TODO: Maybe an algorithm to automatically switch to curl if there's a streak of
#      failed pings (so no manual intervention is needed)
#TODO: Try using httplib directly instead of curl
#TODO: Read in settings from a config file every loop, so they can be changed
#      without an awkward "kill" and background process re-launch.
from __future__ import division
import re
import os
import sys
import time
import signal
import argparse
import subprocess
import ConfigParser

OPT_DEFAULTS = {'server':'google.com', 'history_length':5, 'frequency':5,
  'timeout':2}
USAGE = "%(prog)s [options]"
DESCRIPTION = """Track and summarize the recent history of connectivity by
pinging an external server. Can print a textual summary figure to stdout or to
a file, which can be read and displayed by utilities like indicator-sysmonitor.
This allows visual monitoring of real, current connectivity. The current output
looks something like "[*oo**]", showing the results of the most recent five
pings (most recent on the right). *'s indicate successful pings and o's are
dropped pings."""
EPILOG = """"""

DATA_DIRNAME = '.nbsstate'
SILENCE_FILENAME = 'SILENCE'
HISTORY_FILENAME = 'uphistory.txt'
STATUS_FILENAME = 'upsimple.txt'
CONFIG_FILENAME = 'upmonitor.cfg'

def main():

  parser = argparse.ArgumentParser(
    description=DESCRIPTION, usage=USAGE, epilog=EPILOG)
  parser.set_defaults(**OPT_DEFAULTS)

  parser.add_argument('-s', '--server',
    help="""The server to ping. Default: %(default)s""")
  parser.add_argument('-o', '--stdout', action='store_true',
    help="""Print status summary to stdout instead of a file.""")
  parser.add_argument('-f', '--frequency', type=int,
    help="""How frequently to test the connection. Give the interval time in
seconds. Default: %(default)s""")
  parser.add_argument('-l', '--history-length', type=int, metavar='LENGTH',
    help="""The number of previous ping tests to take into account when
calculating the uptime stat. Default: %(default)s""")
  parser.add_argument('-c', '--curl', action='store_true',
    help="""Use curl instead of ping as the connection test.""")
  parser.add_argument('-t', '--timeout', type=int,
    help="""Seconds to wait for a response to each ping. If greater than 
"frequency", the value for "frequency" will be used instead. Default:
%(default)s""")
  parser.add_argument('-L', '--logfile',
    help="""Give a file to log ping history to.""")
  parser.add_argument('-d', '--data-dir', metavar='DIRNAME',
    help='The directory where data will be stored. History data will be kept '
      'in DIRNAME/'+HISTORY_FILENAME+', the status summary will be in '
      'DIRNAME/'+STATUS_FILENAME+', and configuration settings will be written '
      'to DIRNAME/'+CONFIG_FILENAME+'. Default: a directory named '+DATA_DIRNAME
      +' in the user\'s home directory.')

  args = parser.parse_args()
  assert args.timeout <= args.frequency, (
    'Error: sleep time must be longer than ping timeout.'
  )
  if args.curl:
    ping_method = 'curl'
  else:
    ping_method = 'ping'

  # determine file paths
  home_dir = os.path.expanduser('~')
  silence_file = os.path.join(home_dir, DATA_DIRNAME, SILENCE_FILENAME)
  if args.data_dir:
    data_dirpath = args.data_dir
  else:
    data_dirpath = os.path.join(home_dir, DATA_DIRNAME)
  history_filepath = os.path.join(data_dirpath, HISTORY_FILENAME)
  status_filepath = os.path.join(data_dirpath, STATUS_FILENAME)
  config_filepath = os.path.join(data_dirpath, CONFIG_FILENAME)

  # write settings to config file
  write_config(config_filepath, args)

  # attach signal handler to write special status on shutdown
  def invalidate_status():
    with open(status_filepath, 'w') as filehandle:
      filehandle.write('[OFFLINE]')
  def invalidate_and_exit(*args):
    invalidate_status()
    sys.exit()
  for signame in ['SIGINT', 'SIGHUP', 'SIGTERM', 'SIGQUIT']:
    sig = getattr(signal, signame)
    signal.signal(sig, invalidate_and_exit)

  # main loop
  now = int(time.time())
  target = now + args.frequency
  while True:
    if os.path.isfile(silence_file):
      invalidate_status()
      target = sleep(target, args.frequency)
      continue

    # read in history from file
    history = []
    if os.path.isfile(history_filepath):
      history = get_history(history_filepath, args.history_length)
    elif os.path.exists(history_filepath):
      fail('Error: history file "'+history_filepath+'" is a non-file.')
    # remove outdated pings
    now = int(time.time())
    prune_history(history, args.history_length - 1, args.frequency, now=now)

    # ping and get status
    result = ping(args.server, method=ping_method, timeout=args.timeout)
    if result:
      status = 'up'
    else:
      status = 'down'
    history.append((now, status))

    # log result
    if args.logfile:
      with open(args.logfile, 'a') as filehandle:
        if result == 0 or result >= 100:
          filehandle.write("{:d}\t{:d}\n".format(int(result), now))
        else:
          filehandle.write("{:.1f}\t{:d}\n".format(result, now))

    # write new history back to file
    if os.path.exists(history_filepath) and not os.path.isfile(history_filepath):
      fail('Error: history file "'+history_filepath+'" is a non-file.')
    write_history(history_filepath, history)

    # write status stat to file (or stdout)
    if os.path.exists(status_filepath) and not os.path.isfile(status_filepath):
      fail('Error: status file "'+status_filepath+'" is a non-file.')
    status_str = status_format2(history, args.history_length)
    if args.stdout:
      print status_str
    else:
      with open(status_filepath, 'w') as filehandle:
        filehandle.write(status_str.encode('utf8'))

    target = sleep(target, args.frequency)


def write_config(config_filepath, args):
  config = ConfigParser.RawConfigParser()
  config.add_section('ProcessSettings')
  if args.logfile:
    config.set('ProcessSettings', 'logfile', args.logfile)
  config.set('ProcessSettings', 'frequency', args.frequency)
  config.set('ProcessSettings', 'timeout', args.timeout)
  with open(config_filepath, 'wb') as configfile:
    config.write(configfile)


def get_history(history_filepath, history_length):
  """Parse history file, return it in a list of (timestamp, status) tuples.
  "timestamp" is an int and "status" is either "up" or "down". Lines which don't
  conform to "timestamp\tstatus" are skipped. If the file does not exist or is
  empty, an empty list is returned. The list is in the same order as the lines
  in the file.
  """
  history = []
  with open(history_filepath, 'rU') as file_handle:
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
  pings have consistently been sent every "frequency" seconds."""
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
  try:
    return 1000*float(curl_str)
  except ValueError:
    return 0.0


def write_history(history_filepath, history):
  with open(history_filepath, 'w') as filehandle:
    for line in history:
      filehandle.write("{}\t{}\n".format(line[0], line[1]))


def calc_up_stat1(history, history_length):
  up_sum = 0
  down_sum = 0
  for line in history:
    if line[1] == 'up':
      up_sum += 1
    elif line[1] == 'down':
      down_sum += 1
  return up_sum/(up_sum+down_sum)


def calc_up_stat2(history, history_length):
  total = 0
  up_sum = 0
  multiplier = history_length
  for line in reversed(history):
    total += multiplier
    if line[1] == 'up':
      up_sum += multiplier
    multiplier-=1
  return up_sum/total


def write_status(status_filepath, history, history_length):
  status_str = status_format2(history, history_length)
  with open(status_filepath, 'w') as filehandle:
    filehandle.write(status_str.encode('utf8'))


def status_format1(history, history_length):
  up_stat = calc_up_stat2(history, history_length)
  stars_width = 6
  stars = int(round(stars_width*up_stat))
  if stars == 0:
    status_str = 'DOWN'
  elif stars == stars_width:
    status_str = '   100%'
  else:
    status_str = ' ' + ('  ' * (stars_width - stars)) + ('*' * stars)
  return status_str


def status_format2(history, history_length):
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


def fail(message):
  sys.stderr.write(message+"\n")
  sys.exit(1)

if __name__ == '__main__':
  main()
