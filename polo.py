#!/usr/bin/env python3
import argparse
import binascii
import hashlib
import logging
import socket
import sys
import urllib.parse
import marco
assert sys.version_info.major >= 3, 'Python 3 required'

DEFAULT_PORT = 35353
HASH_CONST = b'Bust those caches!'
DNS_HEADER = binascii.unhexlify(
  '8180'  # flags (standard response)
  '0001'  # 1 question
  '0001'  # 1 response
  '0000'  # 0 authority records
  '0000'  # 0 additional records
)
DNS_ANSWER_HEADER = binascii.unhexlify(
  '0001'      # query type: A record
  '0001'      # query class: Internet
  '00000E10'  # TTL: 3600 seconds
)
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
  parser.add_argument('-d', '--dns', action='store_true',
    help='Expect queries in DNS format. Changes the default port to 53.')
  parser.add_argument('-p', '--port', type=int,
    help='Port to listen on. Default: {}'.format(DEFAULT_PORT))
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

  if args.port:
    port = args.port
  elif args.dns:
    port = 53
  else:
    port = DEFAULT_PORT

  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  sock.bind((args.ip, port))
  if logging.getLogger().getEffectiveLevel() < logging.CRITICAL:
    print('Listening on {} port {}..'.format(args.ip, port), file=sys.stderr)

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
        txn_id, message_encoded = split_dns_query(contents)
        message = decode_dns_message(message_encoded)
      except ValueError as error:
        logging.error('Error: Problem parsing incoming query:\n'+str(error))
        continue
      message_bytes = bytes(message, 'utf8')
    else:
      message_bytes = contents
    logging.info('Received from {} port {}: {!r}'.format(addr, port, message_bytes))
    digest = get_hash(hash_const+message_bytes)
    if dns:
      try:
        response = encode_dns_response(txn_id, message_encoded, digest)
      except ValueError as error:
        logging.error('Error: Problem encoding response:\n'+str(error))
        continue
    else:
      response = digest
    sock.sendto(response, (addr, port))
    logging.info('Replied with hash {}'.format(bytes_to_hex(digest)))


def split_dns_query(query):
  txn_id = query[:2]
  header = query[2:2+len(marco.DNS_HEADER)]
  message_encoded = query[2+len(marco.DNS_HEADER):-len(marco.DNS_FOOTER)]
  footer = query[-len(marco.DNS_FOOTER):]
  if header != marco.DNS_HEADER:
    raise ValueError('Malformed query header: {}'.format(header))
  if footer != marco.DNS_FOOTER:
    raise ValueError('Malformed query footer: {}'.format(footer))
  return txn_id, message_encoded


def decode_dns_message(message_encoded):
  fields = []
  message_remaining = message_encoded
  while message_remaining:
    field_len = message_remaining[0]
    field_bytes = message_remaining[1:1+field_len]
    fields.append(str(field_bytes, 'utf8'))
    message_remaining = message_remaining[1+field_len:]
  message_quoted = '.'.join(fields)
  return urllib.parse.unquote_plus(message_quoted)


def encode_dns_response(txn_id, message_encoded, digest):
  response = txn_id + DNS_HEADER + message_encoded + marco.DNS_FOOTER
  header_len = len(txn_id)+len(marco.DNS_HEADER)
  try:
    name_pointer = b'\xc0'+header_len.to_bytes(1, byteorder='big')
  except OverflowError:
    raise ValueError('Header length ({}) won\'t fit into a single byte.'.format(header_len))
  try:
    digest_len = len(digest).to_bytes(2, byteorder='big')
  except OverflowError:
    raise ValueError('Digest length ({}) won\'t fit into two bytes.'.format(digest_len))
  response += name_pointer + DNS_ANSWER_HEADER + digest_len + digest
  return response


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
