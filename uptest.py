#!/usr/bin/python
# TODO: Add testing for wifi hotspot login pages
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
import random
import subprocess
from optparse import OptionParser
import multiprocessing
import Queue


DEFAULTS = {'log_file':'', 'frequency':5, 'curl':False, 'server':'google.com'}
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
  
  server =    options.server
  frequency = options.frequency

  # Stack holding tuples of (process, queue) for each ongoing ping.
  # The plan: push new pings onto the end, and search backwards through them
  # from the end, newest to oldest, and use the first result you find. Then
  # discard that ping and everything older.
  pings = []

  while True:

    print "Starting at the top"
    queue = multiprocessing.Queue()
    process = multiprocessing.Process(target=ping, args=(queue, server))
    # print "firing off another one"
    process.start()

    # print "adding to stack"
    pings.append((process, queue))

    print "checking status"
    print "\t"+str(getstatus(pings))

    # print queue.get()

    # TODO: replace with sleeping 1 sec at a time, waking up, checking clock,
    # and proceeding if it's time.
    # print "going to sleep"
    time.sleep(frequency)
    # print "waking up"
    # time.sleep(1)


def ping(queue, server):

  devnull = open('/dev/null', 'w')

  timestamp = int(time.time())
  print "about to run ping: "+str(timestamp)
  exit_status = subprocess.call(['ping', '-n', '-c', '1', server],
    stdout=devnull, stderr=devnull)
  print "ran it! exit status = "+str(exit_status)

  queue.put([exit_status, timestamp])
  print "put it in the queue!"

  # Safe retrieval idiom taken from: http://stackoverflow.com/a/1541117/726773
  queue.put(None)
  result = []
  for i in iter(queue.get, None):
    result.append(i)

  print result
  
  # try:
  #   result = queue.get(True, 0)
  #   print "got a result from inside! "+str(result)
  # except Queue.Empty:
  #   result = None
  #   print "it threw a Queue.Empty, from inside!"


def pingdummy(queue, server):
  timestamp = int(time.time())
  time.sleep(random.randint(0,10))
  queue.put([0, timestamp])


def getstatus(pings):
  """Return values:
  (exitcode, timestamp) if it finds a finished ping,
  None if not."""

  print "inside, at the top"
  latest = -1
  result = None
  for i in reversed(range(len(pings))):
    process = pings[i][0]
    queue = pings[i][1]
    if not process.is_alive():
      print "found a finished one, trying .get()"
      try:
        result = queue.get(True, 0)
      except Queue.Empty:
        result = None
      if result:
        latest = i
        break
      else:
        print "refused to give me anything"
  print "finished checking them, latest: "+str(latest)

  # if latest < 0:
  #   print "no result"
  #   return None
  # else:
  #   queue = pings[latest][1]
  #   print "finished, about to .get()"
  #   try:
  #     return queue.get(True, 0)
  #   except Queue.Empty:
  #     return None

  return result

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
  # main()
  # testping()
  queue = multiprocessing.Queue()
  process = multiprocessing.Process(target=ping, args=(queue, 'microsoft.com'))
  process.start()

