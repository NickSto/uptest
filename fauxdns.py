#!/usr/bin/env python3
import binascii
import sys
import urllib.parse
assert sys.version_info.major >= 3, 'Python 3 required'

DNS_QUERY_HEADER = binascii.unhexlify(
  '0100'  # flags (standard query)
  '0001'  # 1 question
  '0000'  # 0 answers
  '0000'  # 0 authority records
  '0000'  # 0 additional records
)
DNS_QUERY_FOOTER = binascii.unhexlify(
  '00'    # null-terminate the query field
  '0001'  # query type: A record
  '0001'  # query class: Internet
)
DNS_RESPONSE_HEADER = binascii.unhexlify(
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


def encode_dns_query(message, txn_id):
  if len(txn_id) != 2:
    raise ValueError('Transaction ID {} is not 2 bytes long.'.format(txn_id))
  query = txn_id + DNS_QUERY_HEADER
  query += encode_dns_message(message)
  query += DNS_QUERY_FOOTER
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
  header = response[2:2+len(DNS_RESPONSE_HEADER)]
  if header != DNS_RESPONSE_HEADER:
    raise ValueError('Malformed response header: {}'.format(header))
  # Find the end of the null-terminated query section.
  query_end = 2+len(DNS_RESPONSE_HEADER) + 1
  while query_end < len(response) and response[query_end] != 0:
    query_end += 1
  if query_end >= len(response):
    raise ValueError('Query not null-terminated.')
  query = response[2+len(DNS_RESPONSE_HEADER):query_end+len(DNS_QUERY_FOOTER)]
  answer = response[query_end+len(DNS_QUERY_FOOTER):]
  return txn_id, query, answer


def extract_dns_answer(answer):
  name_pointer = answer[:2]
  header = answer[2:2+len(DNS_ANSWER_HEADER)]
  data_section = answer[2+len(DNS_ANSWER_HEADER):]
  #TODO: Allow different TTLs. Then we can still decode the data and tell that the problem is
  #      caching.
  if header != DNS_ANSWER_HEADER:
    raise ValueError('Malformed response answer header: {}'.format(header))
  data_len = bytes_to_int(data_section[:2])
  if len(data_section) != 2+data_len:
    raise ValueError('Data section in answer is a different length ({}) than declared ({}).'
                     .format(len(data_section)-2, data_len))
  return data_section[2:]


#TODO: If the DNS query is malformed, reply with a DNS error.
#      Can use the RCODE (or "Reply code") section of the flags.
#      FORMERR is probably appropriate (RCODE value 1).

def split_dns_query(query):
  txn_id = query[:2]
  header = query[2:2+len(DNS_QUERY_HEADER)]
  message_encoded = query[2+len(DNS_QUERY_HEADER):-len(DNS_QUERY_FOOTER)]
  footer = query[-len(DNS_QUERY_FOOTER):]
  if header != DNS_QUERY_HEADER:
    raise ValueError('Malformed query header: {}'.format(header))
  if footer != DNS_QUERY_FOOTER:
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
  response = txn_id + DNS_RESPONSE_HEADER + message_encoded + DNS_QUERY_FOOTER
  header_len = len(txn_id)+len(DNS_QUERY_HEADER)
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


def int_to_bytes(integer, length):
  return integer.to_bytes(length, byteorder='big')


def bytes_to_int(bytes_data):
  return int.from_bytes(bytes_data, byteorder='big')
