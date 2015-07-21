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

        proxy = config.bitcoin_proxy(datadir=node_dir)
        try:
            proxy.stop()
        except ConnectionRefusedError:
            print("Connection refused, assume stopped")

        lproxy = config.lightning_proxy(datadir=node_dir)
        try:
            lproxy.stop()
        except requests.exceptions.ConnectionError:
            print("Lightning connection refused, assume stopped")

    time.sleep(1)
    #os.remove(regnet_dir+'/Carol/regtest/wallet.dat')
    shutil.rmtree(regnet_dir)

if __name__ == "__main__":
    main()
