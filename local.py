"""Local (private) API for a lightning node.
Currently this just collects and exposes methods in channel and lightning.
A HTML GUI could also be provided here in the future.
All requests require authentication.
"""

from flask import Blueprint
from jsonrpc.backend.flask import JSONRPCAPI
from serverutil import authenticate_before_request
from jsonrpcproxy import SmartDispatcher
import channel

API = Blueprint('local', __name__, url_prefix='/local')
rpc_api = JSONRPCAPI(SmartDispatcher())
assert type(rpc_api.dispatcher == SmartDispatcher)
API.add_url_rule('/', 'rpc', rpc_api.as_view(), methods=['POST'])
REMOTE = rpc_api.dispatcher.add_method

REMOTE(channel.create)
REMOTE(channel.send)
REMOTE(channel.close)
REMOTE(channel.getbalance)
REMOTE(channel.getcommitmenttransactions)

@REMOTE
def alive():
    """Test if the server is ready to handle requests."""
    return True

API.before_request(authenticate_before_request)
