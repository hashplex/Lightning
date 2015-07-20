#! /usr/bin/env python3

"""A simple json-rpc service proxy with automatic method generation."""

import requests
import json

class JSONResponseException(Exception):
    """Exception returned from RPC call"""

class JSONRPCError(Exception):
    """Error making RPC call"""

# TODO: proper money handling? might belong in the server
class Proxy(object): # pylint: disable=too-few-public-methods
    """Remote method call proxy."""
    def __init__(self, url):
        self.url = url
        self.headers = {'content-type': 'application/json'}
        self._id = 0

    def _call(self, name, *args, **kwargs):
        """Call a method."""
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

        if 'error' in response is not None:
            raise JSONResponseException(response['error'])
        elif 'result' not in response:
            raise JSONRPCError({
                'code': -343, 'message': 'missing JSON-RPC result'})
        else:
            return response['result']

    def _request(self, data):
        """Perform the request."""
        return requests.post(self.url, data=data, headers=self.headers).json()

    # copied from python-bitcoinlib
    def __getattr__(self, name):
        """Generate method stubs as needed."""
        if name.startswith('__') and name.endswith('__'):
            # Python internal stuff
            raise AttributeError

        # Create a callable to do the actual call
        func = lambda *args: self._call(name, *args)

        # Make debuggers show <function bitcoin.rpc.name> rather than <function
        # bitcoin.rpc.<lambda>>
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
