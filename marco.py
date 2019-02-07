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
  parser.add_argument('-d', '--dns', action='store_true',
    help='Disguise the data as a DNS query. Changes the default port to 53.')
  parser.add_argument('-h', '--host', default='127.0.0.1',
    help='Destination host. Give an IP address or domain name. Default: %(default)s')
  parser.add_argument('-p', '--port', type=int,
    help='Port to send to. Default: {}'.format(polo.DEFAULT_PORT))
  parser.add_argument('-t', '--tsv', action='store_const', dest='format', const='computer',
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

  if args.port:
    port = args.port
  elif args.dns:
    port = 53
  else:
    port = polo.DEFAULT_PORT

  #TODO: Use getaddrinfo() to support IPv6.
  ip = socket.gethostbyname(args.host)

  message_bytes = bytes(args.message, 'utf8')
  if args.dns:
    txn_id = get_random_bytes(2)
    message_encoded = fauxdns.encode_dns_query(args.message, txn_id)
  else:
    message_encoded = message_bytes

  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  try:
    start = timeit.default_timer()
    try:
      sock.sendto(message_encoded, (ip, port))
    except OSError:
      logging.critical('Error: Could not connect to remote server.')
      return FAILURE_EXIT_CODE
    logging.info('Sent query; waiting on reply..')
    response, (addr, port) = sock.recvfrom(1024)
    elapsed = timeit.default_timer() - start
    expected_digest = polo.get_hash(message_bytes)
    if args.format == 'human':
      print('Received response from {} port {} in {:0.1f} ms'.format(addr, port, elapsed*1000))
    else:
      print('{:0.1f}'.format(elapsed*1000))
    if args.dns:
      try:
        response_txn_id, query, answer = fauxdns.split_dns_response(response)
        response_digest = fauxdns.extract_dns_answer(answer)
      except ValueError as error:
        logging.warning('Warning: Malformed response. Probably a response from a real DNS server.\n'
                        +str(error))
        return INTERCEPTION_EXIT_CODE
    else:
      response_digest = response
    if response_txn_id != txn_id:
      logging.error('Response transaction ID ({}) is different from query\'s ({}).'
                    .format(fauxdns.bytes_to_int(response_txn_id), fauxdns.bytes_to_int(txn_id)))
    if response_digest == expected_digest:
      if args.format == 'human':
        print('Response is as expected: {}'.format(polo.bytes_to_hex(response_digest)))
    else:
      if args.format == 'human':
        print('Response differs from expected: {}'.format(polo.bytes_to_hex(expected_digest)))
      return CACHING_EXIT_CODE
  finally:
    sock.close()


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
