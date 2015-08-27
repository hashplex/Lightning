"""Micropayment channel API"""

import os.path
import pickle
import collections
import functools
import itertools
import queue
import threading
import leveldb
from flask import Blueprint, current_app
from blinker import Namespace
from jsonrpc.backend.flask import JSONRPCAPI
from bitcoin.core import CMutableOutPoint, CMutableTxOut, CMutableTxIn
from bitcoin.core import CMutableTransaction
from bitcoin.core.scripteval import VerifyScript, SCRIPT_VERIFY_P2SH
from bitcoin.core.script import CScript, SignatureHash, SIGHASH_ALL
from bitcoin.core.script import OP_CHECKMULTISIG, OP_PUBKEY
from bitcoin.wallet import CBitcoinAddress, CBitcoinSecret
import bitcoin.rpc
import jsonrpcproxy

signals = Namespace()
channel_opened = signals.signal("channel_opened")

tasks = queue.Queue()

class AnchorScriptSig(object):
    """Class representing a scriptSig satisfying the anchor output.
    Uses OP_PUBKEY to hold the place of your signature.
    """

    def __init__(self, my_index=0, sig=b'', redeem=b''):
        if my_index == b'':
            my_index = 0
        if my_index not in [0, 1]:
            raise Exception("Unknown index", my_index)
        self.my_index = my_index
        self.sig = sig
        self.redeem = CScript(redeem)

    @classmethod
    def from_script(cls, script):
        """Construct an AnchorScriptSig from a CScript."""
        script = list(script)
        assert len(script) == 4
        if script[1] == OP_PUBKEY:
            return cls(0, script[2], script[3])
        elif script[2] == OP_PUBKEY:
            return cls(1, script[1], script[3])
        else:
            raise Exception("Could not find OP_PUBKEY")

    def to_script(self, sig=OP_PUBKEY):
        """Construct a CScript from an AnchorScriptSig."""
        if self.my_index == 0:
            sig1, sig2 = sig, self.sig
        elif self.my_index == 1:
            sig1, sig2 = self.sig, sig
        else:
            raise Exception("Unknown index", self.my_index)
        return CScript([0, sig1, sig2, self.redeem])

class FunctionTable(dict):
    """Map keys to functions with decorator syntax."""

    def add(self, key):
        """Add a key-value pair by decorator."""
        def wrapper(func):
            """Add func as a value."""
            self[key] = func
            return func
        return wrapper

class Channel(object):
    """A micro-payment channel control block / state machine."""

    table = FunctionTable()
    private_key = None
    bitcoind = None

    def __init__(self, address):
        self.address = address
        self.state = 'begin'
        self.deferred = collections.deque()
        self.anchor = CMutableTxIn()
        self.our = CMutableTxOut()
        self.their = CMutableTxOut()
        self.cmd_id = None

    @classmethod
    def select_coins(cls, amount):
        """Get a txin set and change to spend amount."""
        coins = cls.bitcoind.listunspent()
        out = []
        for coin in coins:
            if not coin['spendable']:
                continue
            out.append(CMutableTxIn(coin['outpoint']))
            amount -= coin['amount']
            if amount <= 0:
                break
        if amount > 0:
            raise Exception("Not enough money")
        change = CMutableTxOut(
            -amount, cls.bitcoind.getrawchangeaddress().to_scriptPubKey())
        return out, change

    @staticmethod
    def anchor_script(my_pubkey, their_pubkey):
        """Generate the output script for the anchor transaction."""
        script = CScript([2, my_pubkey, their_pubkey, 2, OP_CHECKMULTISIG])
        return script

    @property
    def bob(self):
        """Proxy to counterpary."""
        return jsonrpcproxy.Proxy(self.address+'channel/')

    def sig_for_them(self):
        """Generate a signature for the mirror commitment transaction."""
        transaction = CMutableTransaction([self.anchor], [self.their, self.our])
        transaction = CMutableTransaction.from_tx(transaction) # copy
        # convert scripts to CScript
        transaction.vin[0].scriptSig = transaction.vin[0].scriptSig.to_script()
        for tx_out in transaction.vout:
            tx_out.scriptPubKey = tx_out.scriptPubKey.to_scriptPubKey()
        # sign
        sighash = SignatureHash(self.anchor.scriptSig.redeem, transaction, 0, SIGHASH_ALL)
        sig = self.private_key.sign(sighash) + bytes([SIGHASH_ALL])
        return sig

    def handle(self, task):
        """Handle one task (input event for the state machine)."""
        name, args, kwargs = task
        self.table[name](*args, **kwargs)
        while self.state == 'normal' and self.deferred:
            name, args, kwargs = self.deferred.popleft()
            self.table[name](*args, **kwargs)

    def defer(self, task):
        """Record a task to be done when back in normal state."""
        self.deferred.append(task)

    @table.add('cmd_open')
    def open(self, cmd_id, my_money, their_money, fees=10000):
        """Start the opening process."""
        assert self.state == 'begin'
        self.cmd_id = cmd_id
        coins, change = self.select_coins(my_money + 2 * fees)
        pubkey = self.private_key.pub
        self.our.scriptPubKey = self.bitcoind.getnewaddress()
        self.our.nValue = my_money
        self.their.nValue = their_money
        self.bob.open_channel(their_money, my_money, fees,
                              coins, change,
                              pubkey, self.our.scriptPubKey)
        self.state = 'open_wait_1'

    @table.add('pkt_open_channel')
    def open_channel(self, my_money, their_money, fees, their_coins,
                     their_change, their_pubkey, their_addr):
        """Respond to a requested open."""
        assert self.state == 'begin'
         # Get inputs and change output
        coins, change = self.select_coins(my_money + 2 * fees)
        # Make the anchor script
        anchor_output_script = self.anchor_script(self.private_key.pub, their_pubkey)
        # Construct the anchor utxo
        payment = CMutableTxOut(my_money + their_money + 2 * fees,
                                anchor_output_script.to_p2sh_scriptPubKey())
        # Anchor tx
        transaction = CMutableTransaction(
            their_coins + coins,
            [payment, change, their_change])
        # Half-sign
        transaction = self.bitcoind.signrawtransaction(transaction)['tx']
        # Create channel in DB
        self.anchor.prevout = CMutableOutPoint(transaction.GetHash(), 0)
        self.anchor.scriptSig = AnchorScriptSig(0, b'', anchor_output_script)
        self.our.nValue = my_money
        self.our.scriptPubKey = self.bitcoind.getnewaddress()
        self.their.nValue = their_money
        self.their.scriptPubKey = their_addr
        # Event: channel opened
        channel_opened.send(self.cmd_id, address=self.address)
        self.bob.open_accept(transaction, anchor_output_script, self.our.scriptPubKey)
        self.state = 'open_wait_anchor_1.5'

    @table.add('pkt_open_accept')
    def open_accept(self, transaction, redeem, their_addr):
        """Counterparty accepted open."""
        assert self.state == 'open_wait_1'
        transaction = self.bitcoind.signrawtransaction(transaction)
        assert transaction['complete']
        transaction = transaction['tx']
        self.bitcoind.sendrawtransaction(transaction)
        self.bob.update_anchor(transaction.GetHash(), self.sig_for_them())
        self.their.scriptPubKey = their_addr
        self.anchor.scriptSig = AnchorScriptSig(1, b'', redeem)
        self.state = 'open_wait_2'

    @table.add('pkt_update_anchor')
    def update_anchor(self, txid, their_sig):
        """Record the anchor txid."""
        assert self.state == 'open_wait_1.5'
        self.anchor.prevout.hash = txid
        self.anchor.scriptSig.sig = their_sig
        self.bob.anchor_update_sig(self.sig_for_them())
        self.state = 'normal'

    @table.add('pkt_anchor_update_sig')
    def anchor_update_sig(self, sig):
        """Record their signature."""
        assert self.state == 'open_wait_2'
        self.anchor.scriptSig.sig = sig
        channel_opened.send(self.cmd_id)
        self.state = 'normal'

def task_handler(database, bitcoind_address):
    """Task handler thread main function."""
    Channel.bitcoind = bitcoin.rpc.Proxy(bitcoind_address)
    try:
        root_key = database.Get(b'root_key')
    except KeyError:
         # TODO: grab a real private key from bitcoind
        root_key = CBitcoinSecret.from_secret_bytes(bitcoind_address)
        database.Put(b'root_key', root_key)
    Channel.private_key = root_key
    while True:
        address, task = tasks.get()
        try:
            channel = pickle.loads(database.Get(address))
        except KeyError:
            channel = Channel(address)
        channel.handle(task)
        database.Put(address, pickle.dumps(channel))

API = Blueprint('channel', __name__, url_prefix='/channel')
@API.before_app_first_request
def set_up():
    """Start task_handler thread."""
    database = current_app.config['channel_database']
    bitcoind = current_app.config['bitcoind_address']
    threading.Thread(target=lambda: task_handler(database, bitcoind), daemon=True)
@API.record_once
def on_register(state):
    """Create the database."""
    database_path = os.path.join(state.app.config['datadir'], 'channel.dat')
    state.app.config['channel_database'] = leveldb.LevelDB(database_path)

class QueueDispatcher(object):
    """Put messages in the task queue."""

    def __getitem__(self, key):
        def queue_dispatched(address, *args, **kwargs):
            """Put a task in the queue."""
            tasks.put((address, ('pkt_'+key, args, kwargs)))
            return True
        return queue_dispatched
rpc_api = JSONRPCAPI(QueueDispatcher())
assert type(rpc_api.dispatcher == QueueDispatcher)
API.add_url_rule('/', 'rpc', rpc_api.as_view(), methods=['POST'])

uid_lock = threading.Lock()
uid = itertools.count()
def get_uid():
    """Get a unique task identifier (thread-safe)."""
    with uid_lock:
        out = next(uid)
    return out

def create(address, my_money, their_money):
    """Create a payment channel."""
    tasks.put((address, ('cmd_open', (get_uid(), my_money, their_money), {})))

def send(address, amount):
    """Send money."""
    tasks.put((address, ('cmd_send', (get_uid(), amount,), {})))

def close(address):
    """Close the channel."""
    tasks.put((address, ('cmd_close', (get_uid(),), {})))

def getbalance(address):
    """Get a balance."""
    database = current_app.config['channel_database']
    channel = pickle.loads(database.Get(address))
    return channel.our.nValue

def getcommitmenttransactions(address):
    """Get the list of commitment transactions."""
    database = current_app.config['channel_database']
    channel = pickle.loads(database.Get(address))
    return []
