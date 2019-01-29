#!/usr/bin/env python3
import argparse
import hashlib
import logging
import socket
import sys
assert sys.version_info.major >= 3, 'Python 3 required'

HASH_CONST = b'Bust those caches!'
DESCRIPTION = """Reply to pings from upmonitor clients with expected responses.
This server listens to UDP packets on the given port, and replies with a response derived from the
contents of the packet. Specifically, the response is the SHA-256 hash of the contents prepended
with the string "{}". If the client sends different data in each packet, this should avoid any
caching likely to be found in any captive portal or other intermediaries. And UDP allows easy
measurement of the connection latency by the client.""".format(str(HASH_CONST, 'utf8'))


def make_argparser():
  parser = argparse.ArgumentParser(description=DESCRIPTION)
  parser.add_argument('ip', nargs='?', default='127.0.0.1',
    help='Listen IP address. Default: %(default)s')
  parser.add_argument('-p', '--port', type=int, default=35353,
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
      listen(sock)
  except KeyboardInterrupt:
    logging.info('Interrupted by user.')
  finally:
    sock.close()


def listen(sock, hash_const=HASH_CONST):
  while True:
    data, (addr, port) = sock.recvfrom(1024)
    logging.info('Received from {} port {}: {!r}'.format(addr, port, data))
    digest = get_hash(hash_const+data)
    sock.sendto(digest, (addr, port))
    logging.info('Replied with hash {}'.format(bytes_to_hex(digest)))


def get_hash(data, algorithm='sha256'):
  hasher = hashlib.new(algorithm)
  hasher.update(data)
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
