#! /usr/bin/env python3

import requests
import json

class JSONResponseException(Exception):
    pass

class JSONRPCError(Exception):
    pass

class Proxy(object):
    def __init__(self, url):
        self.url = url
        self.headers = {'content-type': 'application/json'}
        self._id = 0

    def _call(self, name, *args, **kwargs):
        assert not (args and kwargs)
        payload = {
            'method': name,
            'params': kwargs or args,
            'id': self._id,
            'jsonrpc': '2.0'
        }

        response = requests.post(
            self.url, data=json.dumps(payload), headers=self.headers).json()

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

    # copied from python-bitcoinlib
    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            # Python internal stuff
            raise AttributeError

        # Create a callable to do the actual call
        f = lambda *args: self._call(name, *args)

        # Make debuggers show <function bitcoin.rpc.name> rather than <function
        # bitcoin.rpc.<lambda>>
        f.__name__ = name
        return f