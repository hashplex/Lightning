#! /usr/bin/env python3

"""A simple json-rpc service proxy with automatic method generation."""

from functools import wraps
import json
from base64 import b64encode, b64decode
import requests
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

class JSONResponseException(Exception):
    """Exception returned from RPC call"""

class JSONRPCError(Exception):
    """Error making RPC call"""

class Proxy(object): # pylint: disable=too-few-public-methods
    """Remote method call proxy."""
    def __init__(self, url):
        self.url = url
        self.headers = {'content-type': 'application/json'}
        self._id = 0

    def _call(self, name, *args, **kwargs):
        """Call a method."""
        args, kwargs = to_json(args), to_json(kwargs)
        assert not (args and kwargs)
        payload = {
            'method': name,
            'params': kwargs or args,
            'id': self._id,
            'jsonrpc': '2.0'
        }

        response = self._request(json.dumps(payload))

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == self._id

        self._id += 1

        if 'error' in response:
            raise JSONResponseException(from_json(response['error']))
        elif 'result' not in response:
            raise JSONRPCError('missing JSON RPC result')
        else:
            return from_json(response['result'])

    def _request(self, data):
        """Perform the request."""
        return requests.post(self.url, data=data, headers=self.headers).json()

    def __getattr__(self, name):
        """Generate method stubs as needed."""
        func = lambda *args, **kwargs: self._call(name, *args, **kwargs)
        func.__name__ = name
        return func

class AuthProxy(Proxy): # pylint: disable=too-few-public-methods
    """Proxy with basic authentication."""
    def __init__(self, url, auth):
        Proxy.__init__(self, url)
        self.auth = auth

    def _request(self, data):
        """Perform the request."""
        return requests.post(
            self.url, data=data, headers=self.headers, auth=self.auth).json()
