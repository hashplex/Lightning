#! /usr/bin/env python3

"""JSON-RPC tools.

Proxy is a simple RPC client with automatic method generation. It supports
transparent translation of objects specified below.
AuthProxy is the same as proxy but can authenticate itself with basic auth.

SmartDispatcher is a server component which handles transparent translation
of the objects specified below.

Objects supported by transparent (automatic) translation:
* int (standard JSON)
* str (standard JSON)
* None (usually caught by JSON-RPC library for notifications)
* bytes
* bitcoin.base58.CBase58Data
  - bitcoin.wallet.CBitcoinAddress
* bitcoin.core.Serializable
  - bitcoin.core.CMutableTransaction
  - bitcoin.core.CMutableTxIn
  - bitcoin.core.CMutableTxOut
* list, tuple (converted to list) (recursive)
* dict (not containing the key '__class__') (recursive)
"""

from functools import wraps
import json
from base64 import b64encode, b64decode
import requests
from jsonrpc.dispatcher import Dispatcher
import bitcoin.core
from bitcoin.core.serialize import Serializable
import bitcoin.wallet
import bitcoin.base58

def serialize_bytes(bytedata):
    """Convert bytes to str."""
    return b64encode(bytedata).decode()

def deserialize_bytes(b64data):
    """Convert str to bytes."""
    return b64decode(b64data.encode())

def subclass_hook(encode, decode, allowed):
    """Generate encode/decode functions for one interface."""
    lookup = {cls.__name__:cls for cls in allowed}
    def encode_subclass(message):
        """Convert message to JSON."""
        for cls in allowed:
            if isinstance(message, cls):
                return {'subclass':cls.__name__,
                        'value':encode(message)}
        raise Exception("Unknown message type", type(message).__name__)
    def decode_subclass(message):
        """Recover message from JSON."""
        cls = lookup[message['subclass']]
        return decode(cls, message['value'])
    return encode_subclass, decode_subclass

HOOKS = [
    (bitcoin.base58.CBase58Data, subclass_hook(
        str,
        lambda cls, message: cls(message),
        [
            bitcoin.wallet.CBitcoinAddress,
            bitcoin.base58.CBase58Data,
        ])),
    (bytes, subclass_hook(
        serialize_bytes,
        lambda cls, message: cls(deserialize_bytes(message)),
        [
            bytes,
        ])),
    (Serializable, subclass_hook(
        lambda message: serialize_bytes(message.serialize()),
        lambda cls, message: cls.deserialize(deserialize_bytes(message)),
        [
            bitcoin.core.CMutableTransaction,
            bitcoin.core.CTransaction,
            bitcoin.core.CMutableTxIn,
            bitcoin.core.CMutableTxOut,
        ])),
]

def to_json(message):
    """Prepare message for JSON serialization."""
    if isinstance(message, list) or isinstance(message, tuple):
        return [to_json(sub) for sub in message]
    elif isinstance(message, dict):
        assert '__class__' not in message
        return {to_json(key):to_json(message[key]) for key in message}
    elif isinstance(message, int) or isinstance(message, str):
        return message
    elif message is None:
        return {'__class__':'None'}
    else:
        for cls, codes in HOOKS:
            if isinstance(message, cls):
                out = codes[0](message)
                assert '__class__' not in out
                out['__class__'] = cls.__name__
                return out
        raise Exception("Unable to convert", message)

def from_json(message):
    """Retrieve an object from JSON message (undo to_json)."""
    if isinstance(message, list) or isinstance(message, tuple):
        return [from_json(sub) for sub in message]
    elif isinstance(message, int) or isinstance(message, str):
        return message
    elif isinstance(message, dict):
        if '__class__' not in message:
            return {from_json(key):from_json(message[key]) for key in message}
        elif message['__class__'] == 'None':
            return None
        else:
            for cls, codes in HOOKS:
                if message['__class__'] == cls.__name__:
                    return codes[1](message)
    raise Exception("Unable to convert", message)

class SmartDispatcher(Dispatcher):
    """Wrap methods to allow complex objects in JSON RPC calls."""

    def __bool__(self): # pylint: disable=no-self-use
        return True

    def __getitem__(self, key):
        """Override __getitem__ to support transparent translation.

        Translate function arguments, return value, and exceptions.
        """
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
