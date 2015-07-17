#! /usr/bin/env python3

import os
import os.path
import subprocess
from textwrap import dedent
import itertools
import shutil

import destroyRegnet
destroyRegnet.main()

bitcoinConfiguration = """\
# Configuration for %(node)s
testnet=0
regtest=1
txindex=1
daemon=1
listen=1

walletnotify=%(walletnotify)s %(node)s %%s
rpcuser=%(node)s
rpcpassword=%(password)s
rpcport=%(rpcport)d
port=%(port)d
"""

lightningConfiguration = """\
# Lightning configuration for %(node)s
daemon=1

rpcport=%(rpcport)d
port=%(port)d
"""

def main():
    ports = ((18412 + i, 18414 + i, 18416 + i, 18418 + i)
             for i in itertools.count(0, 10))
    
    walletnotify = os.path.abspath('walletnotify.sh')
    assert os.path.isfile(walletnotify)

    bitcoind = os.path.abspath('bitcoind')
    assert os.path.isfile(bitcoind)
    lightningd = os.path.abspath('lightningd.py')
    assert os.path.isfile(lightningd)

    regnetDir = os.path.abspath('regnet')
    assert not os.path.exists(regnetDir)
    os.mkdir(regnetDir)
    nodes = zip(['Alice', 'Bob', 'Carol'], ports)
    lastNode = None
    for node, ports in nodes:
        port, rpcport, lport, lrpcport = ports
        nodeDir = os.path.join(regnetDir, node)
        os.mkdir(nodeDir)
        try:
            with open(os.path.join(nodeDir, 'bitcoin.conf'), 'w') as f:
                f.write(bitcoinConfiguration % {
                    'node': node,
                    'password': node, # insecure, but this is regtest
                    'rpcport': rpcport,
                    'port': port,
                    'walletnotify': walletnotify,
                })
                #Connect in a chain
                if lastNode is not None:
                    f.write("connect=localhost:%d\n" % lastNode[1][1]) # rpcport

            with open(os.path.join(nodeDir, 'lightning.conf'), 'w') as f:
                f.write(lightningConfiguration % {
                    'node': node,
                    'port': lport,
                    'rpcport': lrpcport,
                })

            lastNode = (node, ports)
        except:
            print("Failed")
            shutil.rmtree(nodeDir)
            raise
        subprocess.check_call([bitcoind, "-datadir=%s" % nodeDir])
        subprocess.check_call([lightningd, "-datadir=%s" % nodeDir])

if __name__ == "__main__":
    main()