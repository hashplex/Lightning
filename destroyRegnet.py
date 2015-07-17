#! /usr/bin/env python3

import os
import subprocess
import shutil
import time
import bitcoin.rpc
import requests
import json
from configparser import ConfigParser
import config
import jsonrpcproxy

def main():
    regnetDir = os.path.abspath('regnet')
    if not os.path.isdir(regnetDir):
        return
    
    for node in os.listdir(regnetDir):
        nodeDir = os.path.join(regnetDir, node)
        assert os.path.isdir(nodeDir)
        
        bitcoinConfig = config.bitcoin(datadir=nodeDir)
        proxy = bitcoin.rpc.Proxy('http://%s:%s@localhost:%d' %
                                  (bitcoinConfig.get('rpcuser'), 
                                   bitcoinConfig.get('rpcpassword'),
                                   bitcoinConfig.getint('rpcport')))
        try:
            proxy.stop()
        except ConnectionRefusedError:
            print("Connection refused, assume stopped")
        
        lightningConfig = config.lightning(datadir=nodeDir)
        lproxy = jsonrpcproxy.Proxy('http://a:a@localhost:%d' %
                                    (lightningConfig.getint('rpcport'),))
        try:
            lproxy.stop()
        except requests.exceptions.ConnectionError:
            print("Lightning connection refused, assume stopped")

    time.sleep(1)
    shutil.rmtree(regnetDir)

if __name__ == "__main__":
    main()