#!/usr/bin/python
import os
import sys
from optparse import OptionParser
from multiprocessing import Process


DEFAULTS = {'log_file':'', 'frequency':5, 'curl':False, 'server':'google.com'}
USAGE = """Usage: %prog -f 15 -l path/to/log.txt -s server.com"""
DESCRIPTION = """This periodically tests your connection, showing whether your
Internet is currently up or down. It works by testing if it can reach an
external server, to make sure there is no block at any point in your connection.
Dropped packets mean it's "down", returned ones mean it's "up". Latency isn't
taken into account.
All options are optional."""
EPILOG=""""""


def fail(message):
  sys.stderr.write(message+"\n")
  sys.exit(1)


def get_options(defaults, usage, description='', epilog=''):
  """Get options, print usage text."""

  parser = OptionParser(usage=usage, description=description, epilog=epilog)

  parser.add_option('-l', '--log-file', dest='log_file',
      default=defaults.get('log_file'),
      help='Log file to record connectivity history.')
  parser.add_option('-f', '--frequency', dest='frequency', type='int',
    default=defaults.get('frequency'),
    help=('Frequency of connection tests. Give the number of '
      +'seconds in-between tests (pings, curls, etc). Default: %default sec'))
  parser.add_option('-s', '--server', dest='server',
      default=defaults.get('server'),
      help='The server to query with ping/curl. The only sure test '
      +'of connectivity is to try to reach a remote host. Default is %default.')
  parser.add_option('-c', '--curl', dest='curl', action='store_const',
    const=not(defaults.get('curl')), default=defaults.get('curl'),
    help=('Use curl instead of ping as the connectivity test. Ping '
      +'is blocked on some (silly) networks, but web requests never are. This '
      +'makes a HEAD request (option -I), which only asks the server to return '
      +'a header (in order to go easy on the server).'))

  (options, arguments) = parser.parse_args()

  return (options, arguments)


def main():

  (options, arguments) = get_options(DEFAULTS, USAGE, DESCRIPTION, EPILOG)
  



if __name__ == "__main__":
  main()