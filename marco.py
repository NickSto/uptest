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
import polo
assert sys.version_info.major >= 3, 'Python 3 required'

DEFAULT_PORT = 35353
FAILURE_EXIT_CODE = 7
CACHING_EXIT_CODE = 13
INTERCEPTION_EXIT_CODE = 17
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
DESCRIPTION = """Query a server to check the connection between this machine and the Internet.
Uses a special UDP protocol to avoid caching."""
EPILOG = """This will exit with the code 0 on a successful check (the connection works), {} if no
connection can be made, and {} if caching is detected. If the the packet gets lost, this will hang.
""".format(FAILURE_EXIT_CODE, CACHING_EXIT_CODE)


def make_argparser():
  parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EPILOG, add_help=False)
  parser.add_argument('message', nargs='?', default=get_rand_string(12),
    help='Data to send. If not given, this will send a random string.')
  parser.add_argument('-d', '--dns', action='store_true',
    help='Disguise the data as a DNS query. Changes the default port to 53.')
  parser.add_argument('-h', '--host', default='127.0.0.1',
    help='Destination host. Give an IP address or domain name. Default: %(default)s')
  parser.add_argument('-p', '--port', type=int,
    help='Port to send to. Default: {}'.format(DEFAULT_PORT))
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
    port = DEFAULT_PORT

  #TODO: Use getaddrinfo() to support IPv6.
  ip = socket.gethostbyname(args.host)

  message_bytes = bytes(args.message, 'utf8')
  if args.dns:
    txn_id = get_random_bytes(2)
    message_encoded = encode_dns_query(args.message, txn_id=txn_id)
  else:
    message_encoded = message_bytes

  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  try:
    start = time.time()
    try:
      sock.sendto(message_encoded, (ip, port))
    except OSError:
      logging.critical('Error: Could not connect to remote server.')
      return FAILURE_EXIT_CODE
    logging.info('Sent query; waiting on reply..')
    response, (addr, port) = sock.recvfrom(1024)
    elapsed = time.time() - start
    expected_digest = get_hash(HASH_CONST+message_bytes)
    if args.format == 'human':
      print('Received response from {} port {} in {:0.1f} ms'.format(addr, port, elapsed*1000))
    else:
      print('{:0.1f}'.format(elapsed*1000))
    if args.dns:
      try:
        response_txn_id, query, answer = split_dns_response(response)
        response_digest = extract_dns_answer(answer)
      except ValueError as error:
        logging.warning('Warning: Malformed response. Probably a response from a real DNS server:\n'
                        +str(error))
        return INTERCEPTION_EXIT_CODE
    else:
      response_digest = response
    if response_txn_id != txn_id:
      logging.error('Response transaction ID ({}) is different from query\'s ({}).'
                    .format(bytes_to_int(response_txn_id), bytes_to_int(txn_id)))
    if response_digest == expected_digest:
      if args.format == 'human':
        print('Response is as expected: {}'.format(bytes_to_hex(response_digest)))
    else:
      if args.format == 'human':
        print('Response differs from expected: {}'.format(bytes_to_hex(expected_digest)))
      return CACHING_EXIT_CODE
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
    message_encoded += int_to_bytes(length, 1) + bytes(field, 'utf8')
  return message_encoded


def split_dns_response(response):
  txn_id = response[:2]
  header = response[2:2+len(polo.DNS_HEADER)]
  if header != polo.DNS_HEADER:
    raise ValueError('Malformed response header: {}'.format(header))
  # Find the end of the null-terminated query section.
  query_end = 2+len(polo.DNS_HEADER) + 1
  while query_end < len(response) and response[query_end] != 0:
    query_end += 1
  if query_end >= len(response):
    raise ValueError('Query not null-terminated.')
  query = response[2+len(polo.DNS_HEADER):query_end+len(DNS_FOOTER)]
  answer = response[query_end+len(DNS_FOOTER):]
  return txn_id, query, answer


def extract_dns_answer(answer):
  name_pointer = answer[:2]
  header = answer[2:2+len(polo.DNS_ANSWER_HEADER)]
  data_section = answer[2+len(polo.DNS_ANSWER_HEADER):]
  #TODO: Allow different TTLs. Then we can still decode the data and tell that the problem is
  #      caching.
  if header != polo.DNS_ANSWER_HEADER:
    raise ValueError('Malformed response answer header: {}'.format(header))
  data_len = bytes_to_int(data_section[:2])
  if len(data_section) != 2+data_len:
    raise ValueError('Data section in answer is a different length ({}) than declared ({}).'
                     .format(len(data_section)-2, data_len))
  return data_section[2:]


def get_rand_string(length):
  s = ''
  for i in range(length):
    s += random.choice(string.ascii_letters+string.digits)
  return s


def get_hash(data, algorithm='sha256'):
  hasher = hashlib.new(algorithm)
  hasher.update(data)
  return hasher.digest()


def int_to_bytes(integer, length):
  return integer.to_bytes(length, byteorder='big')


def bytes_to_int(bytes_data):
  return int.from_bytes(bytes_data, byteorder='big')


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
