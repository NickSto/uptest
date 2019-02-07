#!/usr/bin/env python3
import argparse
import binascii
import hashlib
import logging
import socket
import sys
import urllib.parse
import fauxdns
assert sys.version_info.major >= 3, 'Python 3 required'

DEFAULT_PORT = 35353
HASH_CONST = b'Bust those caches!'
DESCRIPTION = """Reply to pings from upmonitor clients with expected responses.
This server listens to UDP packets on the given port, and replies with a response derived from the
contents of the packet. Specifically, the response is the SHA-256 hash of the contents prepended
with the string "{}". If the client sends different data in each packet, this should avoid any
caching likely to be found in any captive portal or other intermediaries. And UDP allows easy
measurement of the connection latency by the client.""".format(str(HASH_CONST, 'utf8'))
EPILOG = """Listening directly on port 53 is not recommended, since it requires running this script
as root. If you'd like to receive queries on port 53, you should instead use iptables to redirect
traffic from port 53 to the port this is listening on. If this is listening to {0}, then you can
use: $ sudo iptables -t nat -I PREROUTING --src 0/0 -p udp --dport 53 -j REDIRECT --to-ports {0}
""".format(DEFAULT_PORT)

def make_argparser():
  parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EPILOG)
  parser.add_argument('ip', nargs='?', default='127.0.0.1',
    help='Listen IP address. Default: %(default)s')
  parser.add_argument('-d', '--dns', action='store_true',
    help='Expect queries in DNS format. The contents will be in the place where the domain name is '
         'given in a DNS query. This script will then respond with a DNS response, encoding the '
         'hash where the IP address is normally given.')
  parser.add_argument('-p', '--port', type=int, default=DEFAULT_PORT,
    help='Port to listen on. Default: %(default)s')
  parser.add_argument('-l', '--log', type=argparse.FileType('w'), default=sys.stderr,
    help='Print log messages to this file instead of to stderr. Warning: Will overwrite the file.')
  volume = parser.add_mutually_exclusive_group()
  volume.add_argument('-q', '--quiet', dest='volume', action='store_const', const=logging.CRITICAL,
    default=logging.WARNING)
  volume.add_argument('-v', '--verbose', dest='volume', action='store_const', const=logging.INFO)
  volume.add_argument('-D', '--debug', dest='volume', action='store_const', const=logging.DEBUG)
  return parser


def main(argv):

  parser = make_argparser()
  args = parser.parse_args(argv[1:])

  logging.basicConfig(stream=args.log, level=args.volume, format='%(message)s')

  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  sock.bind((args.ip, args.port))
  if logging.getLogger().getEffectiveLevel() < logging.CRITICAL:
    print('Listening on {} port {}..'.format(args.ip, args.port), file=sys.stderr)

  try:
    while True:
      listen(sock, dns=args.dns)
  except KeyboardInterrupt:
    logging.info('Interrupted by user.')
  finally:
    sock.close()


def listen(sock, hash_const=HASH_CONST, dns=False):
  while True:
    contents, (addr, port) = sock.recvfrom(1024)
    if dns:
      try:
        txn_id, message_encoded = fauxdns.split_dns_query(contents)
        message = fauxdns.decode_dns_message(message_encoded)
      except ValueError as error:
        logging.error('Error: Problem parsing incoming query:\n'+str(error))
        continue
      message_bytes = bytes(message, 'utf8')
    else:
      message_bytes = contents
    logging.info('Received from {} port {}: {!r}'.format(addr, port, message_bytes))
    digest = get_hash(message_bytes, hash_const=HASH_CONST)
    if dns:
      try:
        response = fauxdns.encode_dns_response(txn_id, message_encoded, digest)
      except ValueError as error:
        logging.error('Error: Problem encoding response:\n'+str(error))
        continue
    else:
      response = digest
    sock.sendto(response, (addr, port))
    logging.info('Replied with hash {}'.format(bytes_to_hex(digest)))


def get_hash(data, hash_const=HASH_CONST, algorithm='sha256'):
  hasher = hashlib.new(algorithm)
  hasher.update(hash_const+data)
  return hasher.digest()


def bytes_to_hex(bytes_data):
  hex_data = ''
  for byte in bytes_data:
    hex_data += '{:02x}'.format(byte)
  return hex_data


def fail(message):
  logging.critical(message)
  if __name__ == '__main__':
    sys.exit(1)
  else:
    raise Exception('Unrecoverable error')


if __name__ == '__main__':
  try:
    sys.exit(main(sys.argv))
  except BrokenPipeError:
    pass
