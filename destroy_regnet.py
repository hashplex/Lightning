#! /usr/bin/env python3

"""Clean up the regtest environment from create_regnet.

This can be run from the command line.

main():
Go through each node and kill -9 bitcoind and lightningd based on their pid files.
Then remove the regnet directory.
"""

import os
import shutil
import signal

def stop(pid_path):
    """Stop a process specified in a pid file."""
    if not os.path.isfile(pid_path):
        print(pid_path, "Not found")
    else:
        with open(pid_path) as pid_file:
            pid = int(pid_file.read())
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

def main():
    """Clean up regnet."""
    regnet_dir = os.path.abspath('regnet')
    if not os.path.isdir(regnet_dir):
        return

    for node in os.listdir(regnet_dir):
        node_dir = os.path.join(regnet_dir, node)
        assert os.path.isdir(node_dir)

        stop(os.path.join(node_dir, 'regtest', 'bitcoind.pid'))
        stop(os.path.join(node_dir, 'lightning.pid'))

    shutil.rmtree(regnet_dir, ignore_errors=True)

if __name__ == "__main__":
    main()
