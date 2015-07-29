"""Local (private) API for a lightning node."""

import channel
from jsonrpc.backend.flask import JSONRPCAPI
from flask import Blueprint

API = Blueprint('local', __name__)
RPC_API = JSONRPCAPI()
REMOTE = RPC_API.dispatcher.add_method
API.add_url_rule('/', 'rpc', RPC_API.as_view(), methods=['POST'])

REMOTE(channel.create)
REMOTE(channel.send)
REMOTE(channel.close)
REMOTE(channel.getbalance)

API.add_url_rule('/map', view_func=RPC_API.jsonrpc_map, methods=['GET'])
