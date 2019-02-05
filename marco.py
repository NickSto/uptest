#!/usr/bin/env python3
import argparse
import binascii
import hashlib
import logging
import random
import socket
import string
import sys
import time
import urllib.parse
assert sys.version_info.major >= 3, 'Python 3 required'

DEFAULT_PORT = 35353
HASH_CONST = b'Bust those caches!'
DNS_HEADER = binascii.unhexlify(
  '0100'  # flags (standard query)
  '0001'  # 1 question
  '0000'  # 0 answers
  '0000'  # 0 authority records
  '0000'  # 0 additional records
)
DNS_FOOTER = binascii.unhexlify(
  '00'    # null-terminate the query field
  '0001'  # query type: A record
  '0001'  # query class: Internet
)
DESCRIPTION = """"""


def make_argparser():
  parser = argparse.ArgumentParser(description=DESCRIPTION, add_help=False)
  parser.add_argument('message', nargs='?', default=get_rand_string(12),
    help='Data to send. If not given, this will send a random string.')
  parser.add_argument('-d', '--dns', action='store_true',
    help='Disguise the data as a DNS query. Changes the default port to 53.')
  parser.add_argument('-h', '--host', default='127.0.0.1',
    help='Destination host. Give an IP address or domain name. Default: %(default)s')
  parser.add_argument('-p', '--port', type=int,
    help='Port to send to. Default: {}'.format(DEFAULT_PORT))
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
    port = DEFAULT_PORT

  message_bytes = bytes(args.message, 'utf8')
  if args.dns:
    message_encoded = encode_dns_query(args.message)
  else:
    message_encoded = message_bytes

  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  try:
    start = time.time()
    sock.sendto(message_encoded, (args.host, port))
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


def get_random_bytes(length):
  integers = [random.randint(0, 255) for i in range(length)]
  return bytes(integers)


def encode_dns_query(message, txn_id=None):
  if txn_id is None:
    txn_id = get_random_bytes(2)
  elif len(txn_id) != 2:
    raise ValueError('Transaction ID {} is not 2 bytes long.'.format(txn_id))
  query = txn_id + DNS_HEADER
  query += encode_dns_message(message)
  query += DNS_FOOTER
  return query


def encode_dns_message(message):
  message_encoded = b''
  message_quoted = urllib.parse.quote_plus(message)
  for field in message_quoted.split('.'):
    length = len(field)
    if length >= 256:
      raise ValueError('Message contains a dot-delimited, url-encoded field longer than '
                       '255 characters: {}'.format(field))
    message_encoded += length.to_bytes(1, byteorder='big') + bytes(field, 'utf8')
  return message_encoded


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
