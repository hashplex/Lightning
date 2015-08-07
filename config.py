#! /usr/bin/env python3

"""Parse configuration options for bitcoin and lightning.

bitcoin_config returns the parsed contents of the bitcoin configuration file,
including default values (currently not specified).
lightning_config does the same for a lightning configuration file.

bitcoin_proxy and lightning_proxy return RPC proxies to bitcoind and
lightningd respectively.

collect_proxies returns a ProxySet with proxies to bitcoin and lightning nodes,
a url to the lightning node, and the pid_file of the lightning node.
"""

import os.path
from configparser import ConfigParser
import bitcoin.rpc
import jsonrpcproxy
from collections import namedtuple

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
}
def bitcoin_config(args=None, datadir=DEFAULT_DATADIR, conf="bitcoin.conf"):
    """Parse and return bitcoin config."""
    conf_path = os.path.join(datadir, conf)
    return get_config(args=args, path=conf_path, defaults=BITCOIN_DEFAULTS)

def bitcoin_proxy(args=None, datadir=DEFAULT_DATADIR, conf="bitcoin.conf"):
    """Return a bitcoin proxy pointing to the config."""
    bitcoin_conf = bitcoin_config(args, datadir, conf)
    return bitcoin.rpc.Proxy('http://%s:%s@localhost:%d' %
                             (bitcoin_conf.get('rpcuser'),
                              bitcoin_conf.get('rpcpassword'),
                              bitcoin_conf.getint('rpcport')))

LIGHTNING_DEFAULTS = {
    'daemon':False,
    'port':9333,
    'pidfile':'lightning.pid',
}
def lightning_config(args=None,
                     datadir=DEFAULT_DATADIR,
                     conf="lightning.conf"):
    """Parse and return lightning config."""
    conf_path = os.path.join(datadir, conf)
    return get_config(args=args, path=conf_path, defaults=LIGHTNING_DEFAULTS)

def lightning_proxy(args=None, datadir=DEFAULT_DATADIR, conf="lightning.conf"):
    """Return a lightning proxy pointing to the config."""
    lightning_conf = lightning_config(args, datadir, conf)
    return jsonrpcproxy.AuthProxy(
        'http://localhost:%d/local/' % lightning_conf.getint('port'),
        (lightning_conf.get('rpcuser'),
         lightning_conf.get('rpcpassword')))

ProxySet = namedtuple('ProxySet', ['bit', 'lit', 'lurl', 'lpid'])
def collect_proxies(datadir=DEFAULT_DATADIR):
    """Collect proxies for a given node.

    bit is a proxy to bitcoind
    lit is a proxy to lightningd
    lurl is a url for the lightning node
    lpid is the pid_file of lightningd
    """
    bit = bitcoin_proxy(datadir=datadir)
    lit = lightning_proxy(datadir=datadir)
    lightning_conf = lightning_config(datadir=datadir)
    lurl = 'http://localhost:%d/' % lightning_conf.getint('port')
    lpid = os.path.join(datadir, 'lightning.pid')
    return ProxySet(bit, lit, lurl, lpid)
