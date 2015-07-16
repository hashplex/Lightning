#! /usr/bin/python3

import os
import subprocess
import shutil
import time

def main():
    bitcoincli = os.path.abspath('bitcoin-cli')
    assert os.path.isfile(bitcoincli)

    regnetDir = os.path.abspath('regnet')
    if not os.path.isdir(regnetDir):
        return
    
    for node in os.listdir(regnetDir):
        nodeDir = os.path.join(regnetDir, node)
        assert os.path.isdir(nodeDir)
        subprocess.call([bitcoincli, "-datadir=%s" % nodeDir, "stop"])

    time.sleep(1)
    shutil.rmtree(regnetDir)

if __name__ == "__main__":
    main()