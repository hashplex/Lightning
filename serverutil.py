"""Utility functions for the server."""

from functools import wraps
from base64 import b64encode, b64decode
from flask import current_app, Response, request, Blueprint
from jsonrpc.backend.flask import JSONRPCAPI
from bitcoin.core import CMutableTransaction
from bitcoin.core.serialize import Serializable

# Copied from http://flask.pocoo.org/snippets/8/
def check_auth(username, password):
    """This function is called to check if a username /
    password combination is valid.
    """
    return (username == current_app.config['rpcuser'] and
            password == current_app.config['rpcpassword'])

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
        'Could not verify your access level for that URL.\n'
        'You have to login with proper credentials', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(view):
    """Require basic authentication on requests to this view."""
    @wraps(view)
    def decorated(*args, **kwargs):
        """Decorated version of view that checks authentication."""
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        if request.remote_addr != "127.0.0.1":
            return Response("Access outside 127.0.0.1 forbidden", 403)
        return view(*args, **kwargs)
    return decorated

def authenticate_before_request():
    """before_request callback to perform authentication."""
    return requires_auth(lambda: None)()

def api_factory(name):
    """Construct a Blueprint and a REMOTE decorator to set up an API."""
    api = Blueprint(name, __name__, url_prefix='/'+name)
    rpc_api = JSONRPCAPI()
    api.add_url_rule('/', 'rpc', rpc_api.as_view(), methods=['POST'])
    return api, rpc_api.dispatcher.add_method

def serialize_bytes(bytedata):
    """Convert bytes to str."""
    return b64encode(bytedata).decode()

def deserialize_bytes(b64data):
    """Convert str to bytes."""
    return b64decode(b64data.encode())

RAW_JSON_TYPES = [int, str,]
def to_json(message, field_type=None):
    """Convert a message to JSON"""
    if isinstance(message, list):
        return [to_json(sub, field_type) for sub in message]
    if field_type == None:
        field_type = type(message)
    if field_type in RAW_JSON_TYPES:
        return message
    if issubclass(field_type, bytes):
        return serialize_bytes(message)
    if issubclass(field_type, Serializable):
        return to_json(message.serialize(), bytes)
    raise Exception("Unable to convert", field_type, message)

def from_json(message, field_type):
    """Convert a message from JSON"""
    if isinstance(message, list):
        return [from_json(sub, field_type) for sub in message]
    if field_type in RAW_JSON_TYPES:
        return message
    if issubclass(field_type, bytes):
        return field_type(deserialize_bytes(message))
    if issubclass(field_type, CMutableTransaction):
        # vin and vout remain immutable after deserialize
        return field_type.from_tx(
            field_type.deserialize(from_json(message, bytes)))
    if issubclass(field_type, Serializable):
        return field_type.deserialize(from_json(message, bytes))
    raise Exception("Unable to convert", field_type, message)
