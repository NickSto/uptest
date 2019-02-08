from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import
import os
import re
import json
import random
import socket
import string
import timeit
import urllib
import hashlib
import httplib
import binascii
import subprocess
try:
  import dns.resolver
  import dns.exception
except ImportError:
  pass


# These headers might take care of hotspot caches.
HTTP_HEADERS = {'Cache-Control':'no-cache', 'Pragma':'no-cache'}
HASH_CONST = b'Bust those caches!'


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
  elapsed, response = ping_http(timeout=timeout, server=server, path=path)
  if response is None:
    return 0.0, None
  # Is the response as expected?
  # If only an expected status is given (body is None), only that has to match.
  # If a status and body is given, both have to match.
  if response['status'] == status and (body is None or response['body'] == body):
    expected = True
  else:
    expected = False
  return elapsed, not expected


def ping_with_challenge(server='polo.nstoler.com', path='/uptest/polo', status=200, timeout=2, **kwargs):
  challenge = get_rand_string(16)
  post_data = {'challenge':challenge}
  elapsed, response = ping_http(server=server, path=path, post_data=post_data, timeout=timeout)
  expected_digest = get_hash(bytes(challenge))
  if response['status'] != status:
    return 0.0, None
  try:
    response_data = json.loads(response['body'])
  except ValueError:
    return elapsed, True
  try:
    response_digest = binascii.unhexlify(response_data.get('digest'))
  except TypeError:
    return elapsed, True
  if response_digest == expected_digest:
    return elapsed, False
  else:
    return elapsed, True


def get_hash(data, algorithm='sha256', hash_const=HASH_CONST):
  hasher = hashlib.new(algorithm)
  hasher.update(hash_const+data)
  return hasher.digest()


def ping_http(timeout=2, server='www.gstatic.com', path='/generate_204', buffer=1024, post_data=None):
  # Do the DNS lookup outside the timed portion of the connection, where we only want to measure the
  # TCP handshake, not any needed DNS lookup.
  ip = dns_lookup(server, timeout=timeout)
  # Create the connection object.
  conex = httplib.HTTPConnection(ip, timeout=timeout)
  # Open a connection to the server. connect() just establishes the TCP connection with a
  # SYN, SYN/ACK, ACK handshake, returning after the final ACK is sent. This is essentially
  # immediately after the SYN/ACK arrives, making it a good measure of a single round trip.
  before = timeit.default_timer()
  try:
    conex.connect()
  except (httplib.HTTPException, socket.error):
    return 0.0, None
  after = timeit.default_timer()
  elapsed = round(1000 * (after - before), 1)
  # Make the HTTP request.
  # We have to define the Host header explicitly to avoid it appearing as the IP address.
  # Note: This won't work with HTTPS, since the host will be passed in the SNI.
  headers = HTTP_HEADERS.copy()
  headers['Host'] = server
  if post_data:
    method = 'POST'
    params = urllib.urlencode(post_data)
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
  else:
    method = 'GET'
    params = None
  try:
    conex.request(method, path, params, headers)
  except (httplib.HTTPException, socket.error):
    return 0.0, None
  # Read the HTTP response.
  try:
    response = conex.getresponse()
  except (httplib.HTTPException, socket.error):
    return 0.0, None
  # We have to pass back a dict of response values instead of the response itself because you can't
  # read the response body after the connection is closed.
  response_dict = {'status':response.status, 'body':response.read(buffer)}
  conex.close()
  return elapsed, response_dict


def dns_lookup(domain, timeout=2):
  """Do a DNS lookup with a certain timeout, if possible."""
  try:
    # Try using dns.resolver, if it's installed.
    return dns_lookup_dns(domain, timeout=timeout)
  except NameError:
    # Otherwise, fall back to socket.gethostbyname().
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
  #TODO: Set timeout using signal.alarm():
  #      https://stackoverflow.com/questions/492519/timeout-on-a-python-function-call/494273#494273
  try:
    ip = socket.gethostbyname(domain)
  except (socket.timeout, socket.gaierror):
    return None
  return ip


def get_rand_string(length):
  s = ''
  for i in range(length):
    s += random.choice(string.ascii_letters+string.digits)
  return s
