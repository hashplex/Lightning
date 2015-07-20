#! /usr/bin/env python3

"""Clean up the regtest environment from create_regnet."""

import os
import shutil
import time
import bitcoin.rpc
import requests
import config
import jsonrpcproxy

def main():
    """Clean up regnet."""
    regnet_dir = os.path.abspath('regnet')
    if not os.path.isdir(regnet_dir):
        return

    for node in os.listdir(regnet_dir):
        node_dir = os.path.join(regnet_dir, node)
        assert os.path.isdir(node_dir)

        bitcoin_config = config.bitcoin(datadir=node_dir)
        proxy = bitcoin.rpc.Proxy('http://%s:%s@localhost:%d' %
                                  (bitcoin_config.get('rpcuser'),
                                   bitcoin_config.get('rpcpassword'),
                                   bitcoin_config.getint('rpcport')))
        try:
            proxy.stop()
        except ConnectionRefusedError:
            print("Connection refused, assume stopped")

        lightning_config = config.lightning(datadir=node_dir)
        lproxy = jsonrpcproxy.AuthProxy(
            'http://localhost:%d/local/' % lightning_config.getint('port'),
            (lightning_config.get('rpcuser'),
             lightning_config.get('rpcpassword')))
        try:
            lproxy.stop()
        except requests.exceptions.ConnectionError:
            print("Lightning connection refused, assume stopped")

    time.sleep(1)
    shutil.rmtree(regnet_dir)

if __name__ == "__main__":
    main()
