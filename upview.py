#!/usr/bin/env python
#TODO: Show intercepted pings (0 ms) in output.
from __future__ import division
import os
import sys
import tail
import argparse
import datetime
import ConfigParser

DATA_DIRNAME = '.local/share/nbsdata'
CONFIG_FILENAME = 'upmonitor.cfg'
DROPPED_MSG = '*****DROPPED*****'
STARTUP_MSG = 'Waiting for the next ping result..   \t'

OPT_DEFAULTS = {'past_pings':10}
USAGE = "%(prog)s [options]"
DESCRIPTION = """Watch a running log of pings being written by upmonitor.py. By default, this will
watch the log file specified in the configuration file "~/"""+DATA_DIRNAME+'/'+CONFIG_FILENAME+'".'
EPILOG = """Thanks to Kasun Herath for the Python implementation of 'tail -f', which this relies on:
https://github.com/kasun/python-tail"""

def main():

  # read arguments
  parser = argparse.ArgumentParser(
    description=DESCRIPTION, epilog=EPILOG)
  parser.set_defaults(**OPT_DEFAULTS)
  parser.add_argument('log', metavar='logfile', nargs='?',
    help='The log file to watch instead of the default.')
  parser.add_argument('-n', '--past-pings', metavar='pings', type=int,
    help='How many past pings to output on startup.')
  parser.add_argument('-c', '--config', metavar='configfile.cfg',
    help='The file containing settings info for the upmonitor process, including where to find the '
         'log file. Default: ~/'+DATA_DIRNAME+'/'+CONFIG_FILENAME)
  args = parser.parse_args()

  # determine path to config file
  if args.config:
    config_filepath = args.config
  else:
    config_filepath = os.path.join(os.path.expanduser('~'), DATA_DIRNAME, CONFIG_FILENAME)

  # read config file to get path to log file
  if args.log:
    log_filepath = args.log
  else:
    if not os.path.isfile(config_filepath):
      fail('Error: Config file "'+config_filepath+'" missing.')
    config = ConfigParser.RawConfigParser()
    config.read(config_filepath)
    try:
      log_filepath = config.get('args', 'logfile')
    except ConfigParser.NoOptionError:
      fail('Error: Cannot find a log file. Are you sure upmonitor.py is writing one?')

  # set up the tail, and start following lines appended to the log file
  log_tail = tail.Tail(log_filepath)
  log_tail.register_callback(callback)
  log_tail.register_wait_func(wait_func)
  log_tail.get_last(args.past_pings)
  try:
    log_tail.follow(s=1)
  except KeyboardInterrupt:
    print


def callback(line):
  """Read and interpret a line from the log file and print a display of it.
  This will be called by tail on receiving each line."""
  line = line.strip()
  fields = line.split('\t')
  msg_width = len(DROPPED_MSG)
  format_str = "\n{:<"+str(msg_width)+"s} {}\t"
  if len(fields) >= 2:
    try:
      ms = float(fields[0])
      timestamp = int(fields[1])
    except ValueError:
      fail('Error: unsupported log format.')
    timestr = str(datetime.datetime.fromtimestamp(timestamp))
    if ms == 0:
      sys.stdout.write(format_str.format(DROPPED_MSG, timestr))
    elif ms < 100:
      sys.stdout.write(format_str.format(str(ms)+' ms', timestr))
    else:
      sys.stdout.write(format_str.format(str(int(ms))+' ms', timestr))
  else:
    fail('Error: unsupported log format.')
  sys.stdout.flush()


def wait_func():
  """Print a star to indicate progress toward the next line.
  This is to be called every second while tail is waiting for a line."""
  sys.stdout.write('*')
  sys.stdout.flush()


def fail(message):
  sys.stderr.write(message+"\n")
  sys.exit(1)

if __name__ == '__main__':
  main()
