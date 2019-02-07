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

TCP_PORT = 18088
UDP_PORT = 35353
BUFFER_SIZE = 1024
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
""".format(UDP_PORT)
#TODO: Figure out how to use nginx to proxy connections to a certain host or url to a different
#      port, allowing this to co-exist with a website on the same server!

def make_argparser():
  parser = argparse.ArgumentParser(description=DESCRIPTION, epilog=EPILOG, add_help=False)
  parser.add_argument('ip', nargs='?', default='127.0.0.1',
    help='Listen IP address. Default: %(default)s')
  parser.add_argument('-u', '--udp', dest='protocol', action='store_const', const='udp', default='udp',
    help='Use raw UDP as the protocol (the default).')
  parser.add_argument('-t', '--tcp', dest='protocol', action='store_const', const='tcp',
    help='Use raw TCP as the protocol.')
  parser.add_argument('-d', '--dns', dest='protocol', action='store_const', const='dns',
    help='Use DNS as the protocol. The challenge will be in the place where the domain name is '
         'given in a DNS query. This script will then respond with a DNS response, encoding the '
         'hash where the IP address is normally given.')
  parser.add_argument('-w', '--http', dest='protocol', action='store_const', const='http',
    help='Use HTTP as the protocol.')
  parser.add_argument('-p', '--port', type=int,
    help='Port to listen on. Default for UDP/DNS: {}. Default for TCP/HTTP: {}'
         .format(UDP_PORT, TCP_PORT))
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
  if args.protocol in ('udp', 'dns'):
    transport = 'udp'
    if not args.port:
      port = UDP_PORT
  elif args.protocol in ('tcp', 'http'):
    transport = 'tcp'
    if not args.port:
      port = TCP_PORT

  if args.protocol in ('udp', 'tcp'):
    application = 'raw'
  else:
    application = args.protocol

  if transport == 'udp':
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  elif transport == 'tcp':
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

  sock.bind((args.ip, port))

  if logging.getLogger().getEffectiveLevel() < logging.CRITICAL:
    print('Listening on {} port {}..'.format(args.ip, port), file=sys.stderr)

  try:
    while True:
      if transport == 'udp':
        listen_udp(sock, application)
      elif transport == 'tcp':
        listen_tcp(sock, application)
  except KeyboardInterrupt:
    logging.info('Interrupted by user.')
  finally:
    sock.close()


def listen_udp(sock, application, hash_const=HASH_CONST):
  while True:
    contents, (ip, port) = sock.recvfrom(BUFFER_SIZE)
    if application == 'raw':
      message_bytes = contents
    elif application == 'dns':
      try:
        txn_id, message_encoded = fauxdns.split_dns_query(contents)
        message = fauxdns.decode_dns_message(message_encoded)
      except ValueError as error:
        logging.error('Error: Problem parsing incoming query:\n'+str(error))
        continue
      message_bytes = bytes(message, 'utf8')
    logging.info('Received from {} port {}: {!r}'.format(ip, port, message_bytes))
    digest = get_hash(message_bytes, hash_const=hash_const)
    if application == 'raw':
      response = digest
    elif application == 'dns':
      try:
        response = fauxdns.encode_dns_response(txn_id, message_encoded, digest)
      except ValueError as error:
        logging.error('Error: Problem encoding response:\n'+str(error))
        continue
    sock.sendto(response, (ip, port))
    logging.info('Replied with hash {}'.format(bytes_to_hex(digest)))


def listen_tcp(sock, application, hash_const=HASH_CONST):
  sock.listen()
  connection, (ip, port) = sock.accept()
  with connection:
    contents = b''
    while True:
      logging.debug('Waiting to receive data..')
      buf = connection.recv(BUFFER_SIZE)
      logging.debug('Received {} bytes, ending in: {}'.format(len(buf), buf[-10:]))
      if not buf:
        break
      elif buf.endswith(b'\n'):
        contents += buf[:-1]
        break
      else:
        contents += buf
    message_bytes = contents
    logging.info('Received from {} port {}: {!r}'.format(ip, port, message_bytes))
    if application == 'raw':
      digest = get_hash(message_bytes, hash_const=hash_const)
    elif application == 'http':
      raise NotImplementedError
    connection.sendall(digest)


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
