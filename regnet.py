#! /usr/bin/env python3

"""Manipulate regtest environments."""

import os
import os.path
import shutil
import subprocess
import signal
import itertools
import time
import tempfile
import bitcoin
import bitcoin.rpc
import jsonrpcproxy
bitcoin.SelectParams('regtest')

BITCOIND = os.path.abspath('bitcoind')
assert os.path.isfile(BITCOIND)
LIGHTNINGD = os.path.abspath('lightningd.py')
assert os.path.isfile(LIGHTNINGD)

PORT = itertools.count(18000)

def get_port():
    """Return a (hopefully open) port."""
    return next(PORT)

class BitcoinNode(object):
    """Interface to a bitcoind instance."""

    CACHE_FILES = ['wallet.dat']
    CACHE_DIRS = ['blocks', 'chainstate', 'database']

    def __init__(self, datadir=None, cache=None, peers=None):
        if peers is None:
            peers = []

        if datadir is None:
            self.datadir = tempfile.mkdtemp()
        else:
            os.mkdir(datadir, 0o700)
            self.datadir = datadir

        self.p2p_port = get_port()
        self.rpc_port = get_port()

        with open(os.path.join(self.datadir, 'bitcoin.conf'), 'w') as conf:
            conf.write("regtest=1\n")
            conf.write("rpcuser=rt\n")
            conf.write("rpcpassword=rt\n")
            conf.write("port=%d\n" % self.p2p_port)
            conf.write("rpcport=%d\n" % self.rpc_port)
            for peer in peers:
                conf.write("connect=localhost:%d\n" % peer.p2p_port)

        if cache is not None:
            restore_dir = os.path.join(self.datadir, 'regtest')
            os.mkdir(restore_dir)
            for cached_file in self.CACHE_FILES:
                shutil.copy(os.path.join(cache.name, cached_file),
                            os.path.join(restore_dir, cached_file))
            for cached_dir in self.CACHE_DIRS:
                shutil.copytree(os.path.join(cache.name, cached_dir),
                                os.path.join(restore_dir, cached_dir))

        self.process = subprocess.Popen(
            [
                BITCOIND, '-datadir=%s' % self.datadir, '-debug',
                '-regtest', '-txindex', '-listen', '-relaypriority=0',
                '-discover=0',
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT)

        self.proxy = bitcoin.rpc.Proxy('http://rt:rt@localhost:%d' % self.rpc_port)

    def stop(self, hard=False, cleanup=False):
        """Stop bitcoind."""
        if hard:
            self.process.kill()
        else:
            self.proxy.stop()
            self.process.wait()
        if cleanup:
            self.cleanup()

    def cleanup(self):
        """Remove the files."""
        shutil.rmtree(self.datadir, ignore_errors=True)

    def print_log(self):
        """Print the log file."""
        with open(os.path.join(self.datadir, 'regtest', 'debug.log')) as log:
            print(log.read())

    def cache(self):
        """Return an object which can be used to restart bitcoind.

        This should be called after stopping the node.
        """
        cache_dir = tempfile.TemporaryDirectory()
        restore_dir = os.path.join(self.datadir, 'regtest')
        for cached_file in self.CACHE_FILES:
            shutil.copy(os.path.join(restore_dir, cached_file),
                        os.path.join(cache_dir.name, cached_file))
        for cached_dir in self.CACHE_DIRS:
            shutil.copytree(os.path.join(restore_dir, cached_dir),
                            os.path.join(cache_dir.name, cached_dir))
        return cache_dir

    def sync_state(self):
        """Compare for synchronization across the network."""
        return set(self.proxy.getrawmempool()), self.proxy.getblockcount()

    def generate(self, blocks=1):
        """Generate blocks."""
        self.proxy.generate(blocks)

    def is_alive(self):
        try:
            self.proxy.getinfo()
        except ConnectionRefusedError as err:
            self.proxy = bitcoin.rpc.Proxy('http://rt:rt@localhost:%d' % self.rpc_port)
            return False
        except bitcoin.rpc.JSONRPCException as err:
            if err.error['code'] == -28:
                return False
            else:
                raise
        else:
            return True

class LightningNode(object):
    """Interface to a lightningd instance."""

    def __init__(self, bitcoind, datadir=None):
        self.bitcoind = bitcoind

        if datadir is None:
            self.datadir = tempfile.mkdtemp()
        else:
            os.mkdir(datadir, 0o700)
            self.datadir = datadir

        self.port = get_port()

        with open(os.path.join(self.datadir, 'lightning.conf'), 'w') as conf:
            conf.write("regtest=1\n")
            conf.write("rpcuser=rt\n")
            conf.write("rpcpassword=rt\n")
            conf.write("port=%d\n" % self.port)
            conf.write("bituser=rt\n")
            conf.write("bitpass=rt\n")
            conf.write("bitport=%d\n" % self.bitcoind.rpc_port)

        self.logfile = open(os.path.join(self.datadir, 'lightning.log'), 'w')
        self.process = subprocess.Popen(
            [
                LIGHTNINGD, '-datadir=%s' % self.datadir, '-nodebug'
            ],
            stdin=subprocess.DEVNULL,
            stdout=self.logfile,
            stderr=subprocess.STDOUT)

        self.proxy = jsonrpcproxy.AuthProxy(
            'http://localhost:%d/local/' % self.port,
            ('rt', 'rt'))

    def stop(self, cleanup=False):
        """Kill lightningd."""
        self.process.kill()
        self.logfile.close()
        if cleanup:
            self.cleanup()

    def cleanup(self):
        """Remove the files."""
        shutil.rmtree(self.datadir, ignore_errors=True)

    def print_log(self):
        """Print the log file."""
        with open(os.path.join(self.datadir, 'lightning.log')) as log:
            print(log.read())

class FullNode(object):
    """Combined Lightning and Bitcoin node."""

    def __init__(self, datadir=None, cache=None, peers=None):
        if peers is None:
            peers = []
        self.bitcoin = BitcoinNode(datadir, cache=cache,
                                   peers=[peer.bitcoin for peer in peers])
        self.lightning = LightningNode(self.bitcoin,
                                       os.path.join(self.bitcoin.datadir, 'lightning'))

    @property
    def bit(self):
        """Bitcoin proxy"""
        return self.bitcoin.proxy

    @property
    def lit(self):
        """Lightning proxy"""
        return self.lightning.proxy

    @property
    def lurl(self):
        """Lightning url"""
        return 'http://localhost:%d/' % self.lightning.port

    def stop(self, hard=False, cleanup=False):
        """Stop the node."""
        self.lightning.stop(cleanup=False)
        self.bitcoin.stop(hard, cleanup=False)
        if cleanup:
            self.cleanup()

    def cleanup(self):
        """Remove files."""
        self.lightning.cleanup()
        self.bitcoin.cleanup()

    def print_log(self, bit=True, lit=True):
        """Print logs."""
        if bit:
            self.bitcoin.print_log()
        if lit:
            self.lightning.print_log()

    def cache(self):
        """Return a cache object."""
        return self.bitcoin.cache()

    def sync_state(self):
        """Compare for synchronization across the network."""
        return self.bitcoin.sync_state()

    def generate(self, blocks=1):
        """Generate blocks."""
        self.bitcoin.generate(blocks)

    def is_alive(self):
        return self.bitcoin.is_alive()

class RegtestNetwork(object):
    """Regtest network."""

    def __init__(self, Node=BitcoinNode, degree=3, datadir=None, cache=None):
        if datadir is None:
            self.datadir = tempfile.mkdtemp()
        else:
            os.mkdir(datadir, 0o700)
            self.datadir = datadir
        if cache is None:
            cache = (None, tuple(None for i in range(degree)))
        miner_cache, node_caches = cache # pylint: disable=unpacking-non-sequence
        assert len(node_caches) == degree
        self.miner = Node(os.path.join(self.datadir, 'miner'), cache=miner_cache)
        self.nodes = [Node(os.path.join(self.datadir, 'node%d' % i),
                           cache=node_cache, peers=[self.miner,])
                      for i, node_cache in zip(range(degree), node_caches)]
        while not (all(node.is_alive() for node in self.nodes) and self.miner.is_alive()):
            print("Connect failed")
            time.sleep(0.5)

    def stop(self, hard=False, cleanup=False):
        """Stop all nodes."""
        self.miner.stop(hard=hard, cleanup=False)
        for node in self.nodes:
            node.stop(hard=hard, cleanup=False)
        if cleanup:
            self.cleanup()

    def cleanup(self):
        """Remove files."""
        self.miner.cleanup()
        for node in self.nodes:
            node.cleanup()
        shutil.rmtree(self.datadir, ignore_errors=True)

    def cache(self):
        """Return a cache object."""
        return (self.miner.cache(), tuple(node.cache for node in self.nodes))

    def print_log(self):
        """Print logs."""
        print("Miner:")
        self.miner.print_log()
        for i, node in enumerate(self.nodes):
            print("Node %d:" % i)
            node.print_log()

    def sync(self, sleep_delay=0.1):
        """Synchronize the network."""
        miner_state = self.miner.sync_state
        while any(node.sync_state() != miner_state for node in self.nodes):
            time.sleep(sleep_delay)
            miner_state = self.miner.sync_state()

    def generate(self, count=1):
        """Generate blocks."""
        self.sync()
        self.miner.generate(count)
        self.sync()

    def __getitem__(self, index):
        return self.nodes[index]

def make_cache():
    """Cache the network after generating initial blocks."""
    network = RegtestNetwork(Node=BitcoinNode)
    network.generate(101)
    network.miner.proxy.sendmany(
        "",
        {network[0].proxy.getnewaddress(): 100000000,
         network[1].proxy.getnewaddress(): 100000000,
        })
    network.sync()
    network.stop(hard=False, cleanup=False)
    cache = network.cache()
    network.cleanup()
    return cache

def create(cache=None, datadir=os.path.abspath('regnet')):
    """Create a Lightning network."""
    network = RegtestNetwork(Node=FullNode, cache=cache, datadir=datadir)
    return network

def stop(network):
    """Stop a network"""
    network.stop(hard=False, cleanup=True)

def kill(pid_path):
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

def teardown(datadir=os.path.abspath('regnet')):
    """Clean up a forgotten FullNode network."""
    for node in os.listdir(datadir):
        node_dir = os.path.join(datadir, node)
        assert os.path.isdir(node_dir)

        kill(os.path.join(node_dir, 'regtest', 'bitcoind.pid'))
        kill(os.path.join(node_dir, 'lightning', 'lightning.pid'))

    shutil.rmtree(datadir, ignore_errors=True)

if __name__ == '__main__':
    pass
