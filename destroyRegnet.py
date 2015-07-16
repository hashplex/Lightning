#! /usr/bin/python3

import os
import subprocess
import shutil
import time
import bitcoin.rpc

def main():
    def rpcPort(i):
        return 18412 + 10 * i

    regnetDir = os.path.abspath('regnet')
    if not os.path.isdir(regnetDir):
        return
    
    nodes = sorted(os.listdir(regnetDir))
    for i in range(len(nodes)):
        node = nodes[i]
        nodeDir = os.path.join(regnetDir, node)
        assert os.path.isdir(nodeDir)
        proxy = bitcoin.rpc.Proxy('http://%s:%s@localhost:%d' %
                                  (node, node, rpcPort(i)))
        proxy.stop()

    time.sleep(1)
    shutil.rmtree(regnetDir)

if __name__ == "__main__":
    main()