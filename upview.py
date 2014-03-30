#!/usr/bin/env python
from __future__ import division
import os
import sys
import tail
import argparse
import datetime
import ConfigParser

OPT_DEFAULTS = {}
USAGE = "%(prog)s [options]"
DESCRIPTION = """Watch a running log of pings being written by upmonitor.py."""
EPILOG = """"""

DATA_DIRNAME = '.nbsstate'
CONFIG_FILENAME = 'upmonitor.cfg'
DROPPED_MSG = '*****DROPPED*****'

def main():

  parser = argparse.ArgumentParser(
    description=DESCRIPTION, usage=USAGE, epilog=EPILOG)
  parser.set_defaults(**OPT_DEFAULTS)

  parser.add_argument('log', metavar='logfile', nargs='?',
    help="""The log file. Default: %(default)s""")
  parser.add_argument('-c', '--config', metavar='configfile.cfg',
    help='The file containing settings info for the upmonitor process, '
      'including where to find the log file. Default: ~/'+DATA_DIRNAME+'/'
      +CONFIG_FILENAME)

  args = parser.parse_args()

  if args.config:
    config_filepath = args.config
  else:
    config_filepath = os.path.join(os.path.expanduser('~'), DATA_DIRNAME,
      CONFIG_FILENAME)

  if args.log:
    log_filepath = args.log
  else:
    config = ConfigParser.RawConfigParser()
    config.read(config_filepath)
    try:
      log_filepath = config.get('ProcessSettings', 'logfile')
    except ConfigParser.NoOptionError:
      fail('Error: Cannot find a log file. Are you sure upmonitor.py is '
        'writing one?')

  log_tail = tail.Tail(log_filepath)
  log_tail.register_callback(callback)
  log_tail.register_wait_func(wait_func)
  try:
    log_tail.follow(s=1)
  except KeyboardInterrupt:
    print


def callback(line):
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
  sys.stdout.write('*')
  sys.stdout.flush()


def fail(message):
  sys.stderr.write(message+"\n")
  sys.exit(1)

if __name__ == '__main__':
  main()
