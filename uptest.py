#!/usr/bin/python
# TODO:
# Add fourth status: "waiting.."
# Print how long ago the last finished ping was
# Add testing for wifi hotspot login pages
# - look for expected result from curl
#
# Notes:
# ping exit statuses
#   nonzero:
#     - google.com with no connection
#       - "curl: (6) Couldn't resolve host 'google.com'"
#     - another IP on the LAN that may or may not exist (silent either way)
#       - "From 192.168.7.207 icmp_seq=1 Destination Host Unreachable"
#       - but ping finished and reported statistics (100% packet loss)
#     - no interface is up (no ethernet wire, not on a wifi network)
#       - "connect: Network is unreachable"
#   zero:
#     - localhost (100% response)
import os
import sys
import time
import signal
import random
import datetime
import subprocess
from optparse import OptionParser
import multiprocessing
import Queue


DEFAULTS = {'log_file':'', 'frequency':5, 'curl':False, 'server':'google.com',
  'debug':False}
USAGE = """Usage: %prog -f 15 -l path/to/log.txt -s server.com"""
DESCRIPTION = """This periodically tests your connection, showing whether your
Internet is currently up or down. It works by testing if it can reach an
external server, to make sure there is no block at any point in your connection.
Dropped packets mean it's "down", returned ones mean it's "up". Latency isn't
taken into account.
Note: at the moment it can't detect an intercepted request, such as a wifi
hotspot login page. Even curl only tests that SOME result was returned, not that
it's the correct one.
All options are optional."""
EPILOG=""""""

DOWN_TEXT  = "***********DOWN***********"
UP_TEXT    = "Connected!                "
NO_TEXT    = "no information yet        "
DATEFORMAT = '%Y-%m-%d %I:%M:%S %p'


debug = False
if '-d' in sys.argv or '--debug' in sys.argv: debug = True

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
  parser.add_option('-d', '--debug', dest='debug', action='store_const',
    const=not(defaults.get('debug')), default=defaults.get('debug'),
    help=('Turn on debug mode.'))

  (options, arguments) = parser.parse_args()

  return (options, arguments)


def main():

  (options, arguments) = get_options(DEFAULTS, USAGE, DESCRIPTION, EPILOG)
  
  server    = options.server
  frequency = options.frequency
  log_file  = options.log_file

  signal.signal(signal.SIGINT, sigint_handler)

  # Stack holding tuples of (process, queue) for each ongoing ping.
  # I push new pings onto the end, then search backwards through them from the
  # end, newest to oldest, and use the first result I find. Then I discard that
  # ping and everything older.
  pings = []

  up = None
  last_time = int(time.time()) - 1
  while True:

    if debug: print "Starting at the top of the loop"
    queue = multiprocessing.Queue()
    process = multiprocessing.Process(target=ping, args=(queue, server))
    process.start()

    pings.append((process, queue))

    status = getstatus(pings)

    if status is not None and status[1] > last_time:
      if status[0] == 0:
        up = True
      else:
        up = False
      last_time = status[1]
    date = datetime.datetime.fromtimestamp(float(last_time))

    if up is None:
      sys.stdout.write(NO_TEXT+' ')
    elif up:
      sys.stdout.write(UP_TEXT+' ')
    else:
      sys.stdout.write(DOWN_TEXT+' ')

    sys.stdout.write(date.strftime(DATEFORMAT)+' ')

    sys.stdout.write("\n")

    if log_file:
      writelog(log_file, up)

    # TODO: replace with sleeping 1 sec at a time, waking up, checking clock,
    # and proceeding if it's time.
    time.sleep(frequency)


def ping(queue, server):

  devnull = open('/dev/null', 'w')

  timestamp = int(time.time())
  if debug: print "Starting ping: "+str(timestamp)
  exit_status = subprocess.call(['ping', '-n', '-c', '1', server],
    stdout=devnull, stderr=devnull)

  queue.put([exit_status, timestamp])


def getstatus(pings):
  """Return values:
  (exitcode, timestamp) if it finds a finished ping,
  None if not."""

  latest = -1
  result = None
  for i in reversed(range(len(pings))):
    process = pings[i][0]
    queue = pings[i][1]
    if not process.is_alive():
      result = qget(queue)
      if result is not None:
        latest = i
        break
  if debug: print "latest = "+str(latest)+" out of "+str([i for i in range(len(pings))])
  if debug: print "result = "+str(result)

  if latest >= 0:
    # remove all the pings in the list at or before latest
    for i in reversed(range(0,latest+1)):
      del(pings[i])

  return result


def qget(queue):
  """Because Queue.get() is apparently broken. Alternative retrieval idiom taken
  from: http://stackoverflow.com/a/1541117/726773
  Returns first item in Queue or None, if it was empty. NOTE: no items in the
  Queue can be None."""
  items = []
  queue.put(None) # sentinel for end of Queue
  for item in iter(queue.get, None):
    items.append(item)
  if len(items) > 0:
    return items[0]
  else:
    return None


def writelog(log_file, up):
  """The log file rules/format:
  If up is None, record nothing (no information on connection status)
  If up is True, record a 1
  If up is False, record a 0"""

  timestr = str(int(time.time()))
  if up:
    statusstr = '1'
  else:
    statusstr = '0'

  if up is not None:
    with open(log_file, 'a') as log_fh:
      log_fh.write(statusstr+"\t"+timestr+"\n")


def sigint_handler(signal, frame):
  print
  sys.exit(0)


def fail(message):
  sys.stderr.write(message+"\n")
  sys.exit(1)


def pingdummy(queue, server):
  timestamp = int(time.time())
  time.sleep(random.randint(0,10))
  queue.put([0, timestamp])

def testping():

  queue = multiprocessing.Queue()
  process = multiprocessing.Process(target=ping, args=(queue, 'microsoft.com'))
  process.start()

  done = False
  alive = True
  tries = 0
  while not done:
    alive = process.is_alive()
    if alive:
      # print "Still alive"
      alive = False
    else:
      # print "It says it's dead!"
      try:
        result = queue.get(True, 0)
      except Queue.Empty:
        result = None
      if result:
        done = True
        # print "It .got()! result:"+str(result)
      else:
        pass # print "It refused to .get()."
      tries+=1
      if not done and tries > 5:
        # print "fine, let's join."
        process.join()
        # print "done joining."

    time.sleep(1)

if __name__ == "__main__":
  main()
  # testping()

