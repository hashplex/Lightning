#! /usr/bin/env python3

"""Setup a regtest environment for testing and development."""

import os
import os.path
import subprocess
import itertools
import shutil
import jsonrpcproxy
import config
import destroy_regnet
import time

BITCOIN_CONFIGURATION = """\
# Configuration for %(node)s
testnet=0
regtest=1
txindex=1
daemon=1
listen=1

rpcuser=%(node)s
rpcpassword=%(password)s
rpcport=%(rpcport)d
port=%(port)d
"""

LIGHTNING_CONFIGURATION = """\
# Lightning configuration for %(node)s
daemon=1
debug=0

rpcuser=%(node)s
rpcpassword=%(password)s
port=%(port)d
"""

def main():
    """Set up a regtest network in regnet."""
    destroy_regnet.main()

    ports = ((18412 + i, 18414 + i, 18416 + i)
             for i in itertools.count(0, 10))

    bitcoind = os.path.abspath('bitcoind')
    assert os.path.isfile(bitcoind)
    lightningd = os.path.abspath('lightningd.py')
    assert os.path.isfile(lightningd)

    regnet_dir = os.path.abspath('regnet')
    assert not os.path.exists(regnet_dir)
    os.mkdir(regnet_dir)
    nodes = zip(['Alice', 'Bob', 'Carol'], ports)
    last_node = None
    proxies = []
    for node, ports in nodes:
        port, rpcport, lport = ports
        node_dir = os.path.join(regnet_dir, node)
        os.mkdir(node_dir)
        try:
            with open(os.path.join(node_dir, 'bitcoin.conf'), 'w') as conf:
                conf.write(BITCOIN_CONFIGURATION % {
                    'node': node,
                    'password': node, # insecure, but this is regtest
                    'rpcport': rpcport,
                    'port': port,
                })
                #Connect in a chain
                if last_node is not None:
                    conf.write("connect=localhost:%d\n" % last_node[1][0])

            with open(os.path.join(node_dir, 'lightning.conf'), 'w') as conf:
                conf.write(LIGHTNING_CONFIGURATION % {
                    'node': node,
                    'password': node, # also insecure
                    'port': lport,
                })

            last_node = (node, ports)
        except:
            print("Failed")
            shutil.rmtree(node_dir)
            raise
        subprocess.check_call([bitcoind, "-datadir=%s" % node_dir])
        subprocess.check_call([lightningd, "-datadir=%s" % node_dir])
        proxies.append((config.bitcoin_proxy(datadir=node_dir), 
                        config.lightning_proxy(datadir=node_dir)))
    time.sleep(3)
    return proxies

if __name__ == "__main__":
    main()
