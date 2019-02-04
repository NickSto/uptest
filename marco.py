#!/usr/bin/env python3
import argparse
import hashlib
import logging
import random
import socket
import string
import sys
import time
assert sys.version_info.major >= 3, 'Python 3 required'

HASH_CONST = b'Bust those caches!'
DESCRIPTION = """"""


def make_argparser():
  parser = argparse.ArgumentParser(description=DESCRIPTION)
  parser.add_argument('message', nargs='?', default=get_rand_string(12),
    help='Data to send. If not given, this will send a random string.')
  parser.add_argument('-i', '--ip', default='127.0.0.1',
    help='Destination IP address. Default: %(default)s')
  parser.add_argument('-p', '--port', type=int, default=35353,
    help='Port to send to. Default: %(default)s')
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

  message_bytes = bytes(args.message, 'utf8')

  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  try:
    start = time.time()
    sock.sendto(message_bytes, (args.ip, args.port))
    data, (addr, port) = sock.recvfrom(1024)
    elapsed = time.time() - start
    digest = get_hash(HASH_CONST+message_bytes)
    print('Received response from {} port {} in {:0.1f} ms'.format(addr, port, elapsed*1000))
    if data == digest:
      print('Response is as expected: {}'.format(bytes_to_hex(data)))
    else:
      print('Response differs from expected: {}'.format(bytes_to_hex(digest)))
  finally:
    sock.close()


def get_rand_string(length):
  s = ''
  for i in range(length):
    s += random.choice(string.ascii_letters+string.digits)
  return s


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
  sys.exit(main(sys.argv))
