"""Utility functions for the server.

This includes the interface from the server implementation to the
payment channel and lightning network APIs.

requires_auth -- decorator which makes a view function require authentication
authenticate_before_request -- a before_request callback for auth
api_factory -- returns a flask Blueprint or equivalent, along with a decorator
               making functions availiable as RPCs.
"""

from functools import wraps
from base64 import b64encode, b64decode
from flask import current_app, Response, request, Blueprint
from jsonrpc.backend.flask import JSONRPCAPI
from jsonrpc.dispatcher import Dispatcher
import bitcoin.core
from bitcoin.core.serialize import Serializable

def serialize_bytes(bytedata):
    """Convert bytes to str."""
    return b64encode(bytedata).decode()

def deserialize_bytes(b64data):
    """Convert str to bytes."""
    return b64decode(b64data.encode())

KNOWN_SERIALIZABLE = [
    bitcoin.core.CMutableTransaction,
    bitcoin.core.CTransaction,
    bitcoin.core.CMutableTxIn,
    bitcoin.core.CMutableTxOut,
    ]
SERIALIZABLE_LOOKUP = {cls.__name__:cls for cls in KNOWN_SERIALIZABLE}

def to_json(message):
    """Convert an object to JSON representation."""
    if isinstance(message, list) or isinstance(message, tuple):
        return [to_json(sub) for sub in message]
    elif isinstance(message, dict):
        assert '__class__' not in message
        return {to_json(key):to_json(message[key]) for key in message}
    elif isinstance(message, int) or isinstance(message, str):
        return message
    elif message is None:
        return {'__class__':'None'}
    elif isinstance(message, bytes):
        return {'__class__':'bytes', 'value':serialize_bytes(message)}
    elif isinstance(message, Serializable):
        for cls in KNOWN_SERIALIZABLE:
            if isinstance(message, cls):
                return {'__class__':'Serializable',
                        'subclass':cls.__name__,
                        'value':serialize_bytes(message.serialize())}
        raise Exception("Unknown Serializable %s" % type(message).__name__)
    raise Exception("Unable to convert", message)

def from_json(message):
    """Retrieve an object from JSON representation."""
    if isinstance(message, list) or isinstance(message, tuple):
        return [from_json(sub) for sub in message]
    elif isinstance(message, int) or isinstance(message, str):
        return message
    elif isinstance(message, dict):
        if '__class__' not in message:
            return {from_json(key):from_json(message[key]) for key in message}
        elif message['__class__'] == 'bytes':
            return deserialize_bytes(message['value'])
        elif message['__class__'] == 'Serializable':
            subclass = SERIALIZABLE_LOOKUP[message['subclass']]
            value = subclass.deserialize(deserialize_bytes(message['value']))
            if subclass is bitcoin.core.CMutableTransaction:
                # vin and vout remain immutable after deserialize
                value = bitcoin.core.CMutableTransaction.from_tx(value)
            return value
        elif message['__class__'] == 'None':
            return None
    raise Exception("Unable to convert", message)

class SmartDispatcher(Dispatcher):
    """Wrap methods to allow complex objects in JSON RPC calls."""
    def __bool__(self): # pylint: disable=no-self-use
        return True

    def __getitem__(self, key):
        old_value = Dispatcher.__getitem__(self, key)
        @wraps(old_value)
        def wrapped(*args, **kwargs):
            """Wrap a function in JSON formatting."""
            try:
                return to_json(old_value(*from_json(args),
                                         **from_json(kwargs)))
            except Exception as exception:
                exception.args = to_json(exception.args)
                raise
        return wrapped

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
    """Construct a Blueprint and a REMOTE decorator to set up an API.

    RPC calls are availiable at the url /name/
    """
    api = Blueprint(name, __name__, url_prefix='/'+name)
    rpc_api = JSONRPCAPI(SmartDispatcher())
    assert type(rpc_api.dispatcher == SmartDispatcher)
    api.add_url_rule('/', 'rpc', rpc_api.as_view(), methods=['POST'])
    return api, rpc_api.dispatcher.add_method
