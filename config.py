#! /usr/bin/env python3

import os
import os.path
from configparser import ConfigParser

# TODO: change by OS
defaultDatadir = os.path.expanduser("~/.bitcoin")

def getConfig(args=None, path=None, defaults=None):
    config = ConfigParser()
    if defaults is not None:
        config.read_dict({'config': defaults})

    if path is not None and os.path.isfile(path):
        with open(path) as f:
            confData = f.read()
        config.read_string('[config]\n' + confData)
        assert config.sections() == ['config']
    else:
        print("No configuration file found")

    if args is not None:
        config.read_dict({'config': args})

    return config['config']

bitcoinDefaults = {
    # TODO: add default config
}
def bitcoin(args=None, datadir=defaultDatadir, conf="bitcoin.conf"):
    confPath = os.path.join(datadir, conf)
    return getConfig(args=args, path=confPath, defaults=bitcoinDefaults)

lightningDefaults = {
    'daemon':False,
    'rpcport':9332,
    'port':9333,
}
def lightning(args=None, datadir=defaultDatadir, conf="lightning.conf"):
    confPath = os.path.join(datadir, conf)
    return getConfig(args=args, path=confPath, defaults=lightningDefaults)
