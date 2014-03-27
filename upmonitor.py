#!/usr/bin/env python
#TODO: Try using httplib directly instead of curl
#TODO: Count sleep time by timestamp diff instead of static time.sleep(freq)
#TODO: Write some warning like '[?????]' when shutting down by interrupt or
#      SILENCE file, to make sure it's clear that the previous status is no
#      longer accurate.
from __future__ import division
import re
import os
import sys
import time
import argparse
import subprocess

OPT_DEFAULTS = {'server':'google.com', 'data_dir':None, 'history_length':5,
  'frequency':5, 'timeout':2}
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
      'in DIRNAME/'+HISTORY_FILENAME+' and the status summary will be in '
      'DIRNAME/'+STATUS_FILENAME+'. Default: a directory named "'+DATA_DIRNAME
      +'" in the user\'s home directory.')

  args = parser.parse_args()
  assert args.timeout <= args.frequency, (
    'Error: sleep time must be longer than ping timeout.')

  # determine file paths
  home_dir = os.path.expanduser('~')
  silence_file = os.path.join(home_dir, DATA_DIRNAME, SILENCE_FILENAME)
  if args.data_dir:
    data_dirpath = args.data_dir
  else:
    data_dirpath = os.path.join(home_dir, DATA_DIRNAME)
  history_filepath = os.path.join(data_dirpath, HISTORY_FILENAME)
  status_filepath = os.path.join(data_dirpath, STATUS_FILENAME)

  while True:
    if os.path.isfile(silence_file):
      time.sleep(args.frequency)
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
    if args.curl:
      result = curl(args.server, timeout=args.timeout)
    else:
      result = ping(args.server, timeout=args.timeout)
    if result:
      status = 'up'
    else:
      status = 'down'
    history.append((now, status))

    # log result
    if args.logfile:
      with open(args.logfile, 'a') as filehandle:
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

    time.sleep(args.frequency)


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


def ping(server, timeout=2):
  """Ping "server", and return the ping time in ms.
  If the ping is dropped, returns 0."""
  devnull = open(os.devnull, 'w')
  command = ['ping', '-n', '-c', '1', '-W', str(timeout), server]

  try:
    output = subprocess.check_output(command, stderr=devnull)
    exit_status = 0
  except subprocess.CalledProcessError as cpe:
    output = cpe.output
    exit_status = cpe.returncode
  except OSError:
    output = ''
    exit_status = 1

  if exit_status == 0:
    return parse_ms(output)
  else:
    return 0


def curl(server, timeout=2):
  """Use curl to "ping" the given server, and return the latency in milliseconds.
  The time is the "time_connect" variable of curl's "-w" option (multiplied by
  1000 to get ms). In practice the time is very similar to a simple ping.
  If the http request fails, returns 0."""
  devnull = open(os.devnull, 'w')
  command = ['curl', '-s', '--output', '/dev/null/', '--write-out',
    r'%{time_connect}\n', '--connect-timeout', str(timeout), server]

  try:
    output = subprocess.check_output(command, stderr=devnull)
    exit_status = 0
  except subprocess.CalledProcessError as cpe:
    output = cpe.output
    exit_status = cpe.returncode
  except OSError:
    output = ''
    exit_status = 1

  #TODO: resolve why it's returning 23
  if exit_status == 0 or exit_status == 23:
    try:
      return 1000*float(output.strip())
    except ValueError:
      return 0.0
  else:
    return 0.0



def parse_ms(ping_str):
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


def fail(message):
  sys.stderr.write(message+"\n")
  sys.exit(1)

if __name__ == '__main__':
  main()
