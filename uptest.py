#!/usr/bin/python
"""
Next step:
Change the items in the "pings" list from processes to tuples holding the final
outputs as well as the processes and queues, so I can iterate through it in the
main body instead of being afraid of touching it directly. Each time, I'll have
a method loop through it, checking if processes are done, and saving the results.
See update_status() for the WIP.

Reorganization:
Right now the model is detached from individual pings. Every 5 seconds it wakes
up, checks the recent pings, and updates the status of whether it's up or down,
then reports that. So every 5 seconds it reports the current status, regardless
of what pings have come back or not.
But I need to change it completely, back to a ping-centric model. What's more
useful to report is the individual pings, not the abstract "status". What that
would look like:
Wake up every 0.1 seconds. If it's time for another ping, send one off. Check
the recent pings, find the most recent one that returned a result. If you find
one, check if there are ones before it that you're still waiting on. If so,
print "missing" or something like it for each one. Then print the result for the
one that did return.
- Still not 100% on what to print when, though.
  - In the case where you skip some missing pings
  - Or when you don't find any recent results and you're still waiting.
    - For this I think I can use the same queues uptest.sh gives.
      - After sending a ping, print a newline. Until it gets some results to
        print, you'll be able to visually see that it's hung on a ping.

Interface features uptest.sh has that're still missing here:
* ms each ping took
  - will really require capturing & processing ping stdout
* Printing the *stars* to show time until next ping

TODO:
* Change third status to "waiting.."
* Print how long ago the last finished ping was
* Replace static sleep with sleep based on elapsed clock time
* Change output to one report per ping (see "CURRENT STATUS" for 2013-10-23)
* Add testing for wifi hotspot login pages
  - look for expected result from curl

Notes:
ping exit statuses
  nonzero:
    - google.com with no connection
      - "curl: (6) Couldn't resolve host 'google.com'"
    - another IP on the LAN that may or may not exist (silent either way)
      - "From 192.168.7.207 icmp_seq=1 Destination Host Unreachable"
      - but ping finished and reported statistics (100% packet loss)
    - no interface is up (no ethernet wire, not on a wifi network)
      - "connect: Network is unreachable"
  zero:
    - localhost (100% response)
"""
import re
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
internet is currently up or down. It works by testing if it can reach an
external server, to make sure there is no block at any point in your connection.
Dropped packets mean it's "down", returned ones mean it's "up". Latency isn't
taken into account.
Note: at the moment it can't detect an intercepted request, such as a wifi
hotspot login page. Even curl only tests that SOME result was returned, not that
it's the correct one.
All options are optional."""
EPILOG=""""""

DOWN_TEXT    = "***********DOWN***********"
UP_TEXT      = "Connected!                "
NO_TEXT      = "no information yet        "
DATEFORMAT   = '%Y-%m-%d %I:%M:%S %p'


debug = False
if '-d' in sys.argv or '--debug' in sys.argv:
  debug = True

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
    help=('***NOT IMPLEMENTED YET***\n'
      +'Use curl instead of ping as the connectivity test. Ping '
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

    # Pause so we catch the ping we just sent this time around instead of next
    time.sleep(0.1)

    status = get_status(pings)

    if status is not None and status[1] > last_time:
      if status[1] == 0:
        up = True
      else:
        up = False
      last_time = status[2]
    date = datetime.datetime.fromtimestamp(float(last_time))

    sys.stdout.write("\n")

    if up is None:
      sys.stdout.write(NO_TEXT+' ')
    elif up:
      sys.stdout.write(UP_TEXT+' ')
    else:
      sys.stdout.write(DOWN_TEXT+' ')

    sys.stdout.write(date.strftime(DATEFORMAT)+' ')

    sys.stdout.flush()

    if log_file:
      writelog(log_file, up)

    time.sleep(frequency)


def ping(queue, server):
  """Ping "server", and add result to "queue".
  The result is (ms, exit_status, timestamp), where
  "ms" is the milliseconds the ping too, or None if it failed.
  "exit_status" is the ping's exit code
  "timestamp" is the time the ping was sent."""
  devnull = open(os.devnull, 'w')

  timestamp = int(time.time())
  if debug: print "Starting ping: "+str(timestamp)
  try:
    output = subprocess.check_output(['ping', '-n', '-c', '1', server],
      stderr=devnull)
    exit_status = 0
  except subprocess.CalledProcessError as cpe:
    output = cpe.output
    exit_status = cpe.returncode
  except OSError:
    output = ''
    exit_status = 1

  ms = parse_ms(output)
  queue.put([ms, exit_status, timestamp])


def get_status(pings):
  """Return values:
  (ms, exitcode, timestamp) if it finds a finished ping,
  None if not."""

  latest = -1
  result = None
  for i in reversed(range(len(pings))):
    (process, queue) = pings[i]
    if not process.is_alive():
      # Kludge for Queue being broken. Calling .get() on an empty Queue hangs,
      # so adding None means an empty Queue will just return that None.
      queue.put(None)
      result = queue.get()
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


def update_status(pings):

  for (result, process, queue) in pings:
    if result is None:
      if not process.is_alive():
        # Kludge for Queue being broken. Calling .get() on an empty Queue hangs,
        # so adding None means an empty Queue will just return that None.
        queue.put(None)
        result = queue.get()



def parse_ms(ping_str):
  """Parse out the ms of the ping from the output of `ping -n -c 1`"""
  ping_pattern = r' bytes from .* time=([\d.]+) ?ms'
  for line in ping_str.splitlines():
    match = re.search(ping_pattern, line)
    if match:
      return float(match.group(1))
  return None


def write_log(log_file, up):
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

def test_ping():

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
  # test_ping()

