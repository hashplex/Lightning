#! /usr/bin/python3

import os
import subprocess
from textwrap import dedent

import destroyRegnet
destroyRegnet.main()

configuration = """\
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

def main():
    def rpcPort(i):
        return 18412 + 10 * i
    def port(i):
        return 18414 + 10 * i

    walletnotify = os.path.abspath('walletnotify.sh')
    assert os.path.isfile(walletnotify)

    bitcoind = os.path.abspath('bitcoind')
    assert os.path.isfile(bitcoind)

    regnetDir = os.path.abspath('regnet')
    os.mkdir(regnetDir)
    nodes = ['Alice', 'Bob', 'Carol']
    for i in range(len(nodes)):
        node = nodes[i]
        nodeDir = os.path.join(regnetDir, node)
        os.mkdir(nodeDir)
        with open(os.path.join(nodeDir, 'bitcoin.conf'), 'w') as f:
            f.write(configuration % {
                'node': node,
                'password': node, # insecure, but this is regtest
                'rpcport': rpcPort(i),
                'port': port(i),
                'walletnotify': walletnotify
            })

            #Connect in a chain
            if i > 0:
                f.write("connect=localhost:%d\n" % rpcPort(i - 1))
        subprocess.check_call([bitcoind, "-datadir=%s" % nodeDir])

if __name__ == "__main__":
    main()