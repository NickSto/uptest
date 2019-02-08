import binascii
import json
from django.http import HttpResponse, HttpResponseNotAllowed, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from .polo import get_hash


@csrf_exempt
def reply(request):
  if request.method == 'POST':
    params = request.POST
  elif request.method == 'GET':
    params = request.GET
  else:
    return HttpResponseNotAllowed(['POST', 'GET'])
  txn_id = params.get('txn')
  challenge = params.get('challenge')
  if not challenge:
    return HttpResponseBadRequest('Missing parameters.')
  challenge_bytes = bytes(challenge, 'utf8')
  digest = get_hash(challenge_bytes)
  digest_hex = str(binascii.hexlify(digest), 'ascii')
  response_data = {'txn':txn_id, 'digest':digest_hex}
  return HttpResponse(json.dumps(response_data), content_type='application/json')
