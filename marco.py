#!/usr/bin/env python3
import argparse
import hashlib
import logging
import random
import socket
import string
import sys
import timeit
import fauxdns
import polo
assert sys.version_info.major >= 3, 'Python 3 required'

#TODO: Change of strategy. Seems it might be common for access points to block DNS requests to
#      arbitrary DNS servers (instead of the DHCP one).
#      So instead, maybe go back to TCP, but make the connection manually. Time how long the
#      sock.connect() method takes. In testing, this seems accurate. Yes, it includes the time the
#      system takes to send out the final ACK, but that's a local operation that's very fast.
#      To address caching, use the TCP connection to send the challenge to polo.py.

FAILURE_EXIT_CODE = 7
CACHING_EXIT_CODE = 13
INTERCEPTION_EXIT_CODE = 17
DESCRIPTION = """Query a server to check the connection between this machine and the Internet.
Uses a special UDP protocol to avoid caching."""
EPILOG = """This will exit with the code 0 on a successful check (the connection works), {} if no
connection can be made, and {} if caching is detected. If the the packet gets lost, this will hang.
""".format(FAILURE_EXIT_CODE, CACHING_EXIT_CODE)


def make_argparser():
  parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EPILOG, add_help=False)
  parser.add_argument('message', nargs='?', default=get_rand_string(12)+'.com',
    help='Data to send. If not given, this will send a random string.')
  parser.add_argument('-u', '--udp', dest='protocol', action='store_const', const='udp', default='udp',
    help='Use raw UDP as the protocol (the default).')
  parser.add_argument('-t', '--tcp', dest='protocol', action='store_const', const='tcp',
    help='Use raw TCP as the protocol.')
  parser.add_argument('-d', '--dns', dest='protocol', action='store_const', const='dns',
    help='Use DNS as the protocol. The data will be disguised as a DNS query. Changes the default '
         'port to 53.')
  parser.add_argument('-w', '--http', dest='protocol', action='store_const', const='http',
    help='Use HTTP as the protocol.')
  parser.add_argument('-h', '--host', default='127.0.0.1',
    help='Destination host. Give an IP address or domain name. Default: %(default)s')
  parser.add_argument('-p', '--port', type=int,
    help='Port to send to. Default for UDP/DNS: {}. Default for TCP/HTTP: {}'
         .format(polo.UDP_PORT, polo.TCP_PORT))
  parser.add_argument('-c', '--tsv', action='store_const', dest='format', const='computer',
    default='human',
    help='Print results in computer-readable format. Currently it will just print the latency in '
         'milliseconds.')
  parser.add_argument('-l', '--log', type=argparse.FileType('w'), default=sys.stderr,
    help='Print log messages to this file instead of to stderr. Warning: Will overwrite the file.')
  volume = parser.add_mutually_exclusive_group()
  volume.add_argument('-q', '--quiet', dest='volume', action='store_const', const=logging.CRITICAL,
    default=logging.WARNING)
  volume.add_argument('-v', '--verbose', dest='volume', action='store_const', const=logging.INFO)
  volume.add_argument('-D', '--debug', dest='volume', action='store_const', const=logging.DEBUG)
  parser.add_argument('-H', '--help', action='help',
    help='Show this help message and exit.')
  return parser


def main(argv):

  parser = make_argparser()
  args = parser.parse_args(argv[1:])

  logging.basicConfig(stream=args.log, level=args.volume, format='%(message)s')

  if args.protocol == 'udp':
    transport = 'udp'
    application = 'raw'
  elif args.protocol == 'dns':
    transport = 'udp'
    application = 'dns'
  elif args.protocol == 'tcp':
    transport = 'tcp'
    application = 'raw'
  elif args.protocol == 'http':
    transport = 'tcp'
    application = 'http'

  if args.port:
    port = args.port
  elif transport == 'udp':
    port = polo.UDP_PORT
  elif transport == 'tcp':
    port = polo.TCP_PORT

  #TODO: Use getaddrinfo() to support IPv6.
  ip = socket.gethostbyname(args.host)

  message_bytes = bytes(args.message, 'utf8')
  expected_digest = polo.get_hash(message_bytes)

  if transport == 'udp':
    try:
      response_digest, stats = send_udp(ip, port, args.message, application)
    except ValueError as error:
      logging.warning('Warning: Malformed response. Probably a response from a real DNS server.\n'
                      +str(error))
      return INTERCEPTION_EXIT_CODE
  elif transport == 'tcp':
    response_digest, stats = send_tcp(ip, port, args.message, application)

  if args.format == 'human':
    if transport == 'udp':
      print('Received response from {ip} port {port} in {elapsed:0.1f} ms.'
            .format(**stats))
    elif transport == 'tcp':
      print('Connected to {} port {} in {elapsed:0.1f} ms.'
            .format(ip, port, **stats))
  else:
    print('{elapsed:0.1f}'.format(**stats))

  if response_digest == expected_digest:
    if args.format == 'human':
      print('Response is as expected: {}'.format(polo.bytes_to_hex(response_digest)))
  else:
    if args.format == 'human':
      print('Response differs from expected: {}'.format(polo.bytes_to_hex(expected_digest)))
      logging.info('Expected:                       {}'.format(polo.bytes_to_hex(response_digest)))
    return CACHING_EXIT_CODE


def send_udp(ip, port, message, application):
  if application == 'dns':
    txn_id = get_random_bytes(2)
    message_encoded = fauxdns.encode_dns_query(message, txn_id)
  else:
    message_encoded = bytes(message, 'utf8')
  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  try:
    start = timeit.default_timer()
    try:
      sock.sendto(message_encoded, (ip, port))
    except OSError:
      logging.critical('Error: Could not connect to remote server.')
      return FAILURE_EXIT_CODE
    logging.info('Sent query; waiting on reply..')
    response, (remote_ip, remote_port) = sock.recvfrom(polo.BUFFER_SIZE)
    elapsed = timeit.default_timer() - start
  finally:
    sock.close()
  if application == 'raw':
    response_digest = response
  else:
    response_txn_id, query, answer = fauxdns.split_dns_response(response)
    response_digest = fauxdns.extract_dns_answer(answer)
    if response_txn_id != txn_id:
      logging.error('Response transaction ID ({}) is different from query\'s ({}).'
                    .format(fauxdns.bytes_to_int(response_txn_id), fauxdns.bytes_to_int(txn_id)))
  return response_digest, {'elapsed':elapsed*1000, 'ip':remote_ip, 'port':remote_port}


def send_tcp(ip, port, message, application):
  if application == 'raw':
    message_encoded = bytes(message+'\n', 'utf8')
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    start = timeit.default_timer()
    sock.connect((ip, port))
    end = timeit.default_timer()
    elapsed = end - start
    sock.sendall(message_encoded)
    response = sock.recv(polo.BUFFER_SIZE)
  return response, {'elapsed':elapsed*1000, 'ip':None, 'port':None}


def get_random_bytes(length):
  integers = [random.randint(0, 255) for i in range(length)]
  return bytes(integers)


def get_rand_string(length):
  s = ''
  for i in range(length):
    s += random.choice(string.ascii_letters+string.digits)
  return s


def fail(message):
  logging.critical(message)
  if __name__ == '__main__':
    sys.exit(1)
  else:
    raise Exception('Unrecoverable error')


if __name__ == '__main__':
  sys.exit(main(sys.argv))
