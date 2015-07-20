#! /usr/bin/env python3

"""Parse configuration options for bitcoin and lightning."""

import os.path
from configparser import ConfigParser

# TODO: change by OS
DEFAULT_DATADIR = os.path.expanduser("~/.bitcoin")

def get_config(args=None, path=None, defaults=None):
    """Parse configs from file 'path', returning a dict-like object"""
    config = ConfigParser()
    if defaults is not None:
        config.read_dict({'config': defaults})

    if path is not None and os.path.isfile(path):
        with open(path) as config_file:
            conf_data = config_file.read()
        config.read_string('[config]\n' + conf_data)
        assert config.sections() == ['config']
    else:
        print("No configuration file found")

    if args is not None:
        config.read_dict({'config': args})

    return config['config']

BITCOIN_DEFAULTS = {
    # TODO: add default config
}
def bitcoin(args=None, datadir=DEFAULT_DATADIR, conf="bitcoin.conf"):
    """Parse and return bitcoin config."""
    conf_path = os.path.join(datadir, conf)
    return get_config(args=args, path=conf_path, defaults=BITCOIN_DEFAULTS)

LIGHTNING_DEFAULTS = {
    'daemon':False,
    'port':9333,
}
def lightning(args=None, datadir=DEFAULT_DATADIR, conf="lightning.conf"):
    """Parse and return lightning config."""
    conf_path = os.path.join(datadir, conf)
    return get_config(args=args, path=conf_path, defaults=LIGHTNING_DEFAULTS)
