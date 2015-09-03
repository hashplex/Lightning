"""Micropayment channel API"""

import logging
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
from bitcoin.base58 import CBase58Data
CBase58Data.__getnewargs__ = lambda self: (str(self),) # Support pickle
import bitcoin.rpc
import jsonrpcproxy

logger = logging.getLogger('lightningd.channel')

signals = Namespace()
channel_opened = signals.signal("channel_opened")
cmd_complete = signals.signal("cmd_complete")
task_error = signals.signal("task_error")

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

class AddressedProxy(jsonrpcproxy.Proxy):
    """Call all methods with our address as the first argument."""

    def __init__(self, our_url, their_url):
        self.our_url = our_url
        super(AddressedProxy, self).__init__(their_url)

    def _call(self, name, *args, **kwargs):
        our_url = object.__getattribute__(self, 'our_url')
        if kwargs:
            super(AddressedProxy, self)._call(name, *args, address=our_url, **kwargs)
        else:
            super(AddressedProxy, self)._call(name, our_url, *args, **kwargs)

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
    local_address = None

    def __init__(self, address):
        self.address = address
        self.state = 'begin'
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
        return AddressedProxy(self.local_address, self.address+'channel/')

    def sig_for_them(self):
        """Generate a signature for the mirror commitment transaction."""
        transaction = CMutableTransaction([self.anchor], [self.their, self.our])
        transaction = CMutableTransaction.from_tx(transaction) # copy
        # convert scripts to CScript
        for tx_out in transaction.vout:
            tx_out.scriptPubKey = tx_out.scriptPubKey.to_scriptPubKey()
        # sign
        sighash = SignatureHash(self.anchor.scriptSig.redeem, transaction, 0, SIGHASH_ALL)
        sig = self.private_key.sign(sighash) + bytes([SIGHASH_ALL])
        return sig

    def signed_commitment(self):
        """Return the fully signed commitment transaction."""
        transaction = CMutableTransaction([self.anchor], [self.our, self.their])
        transaction = CMutableTransaction.from_tx(transaction)
        for tx_out in transaction.vout:
            tx_out.scriptPubKey = tx_out.scriptPubKey.to_scriptPubKey()
        sighash = SignatureHash(self.anchor.scriptSig.redeem, transaction, 0, SIGHASH_ALL)
        sig = self.private_key.sign(sighash) + bytes([SIGHASH_ALL])
        transaction.vin[0].scriptSig = transaction.vin[0].scriptSig.to_script(sig)
        # verify signing worked
        VerifyScript(transaction.vin[0].scriptSig,
                     self.anchor.scriptSig.redeem.to_p2sh_scriptPubKey(),
                     transaction, 0, (SCRIPT_VERIFY_P2SH,))
        return transaction

    def unsigned_settlement(self):
        """Generate the settlement transaction."""
        # Put outputs in the order of the inputs, so that both versions are the same
        if self.anchor.scriptSig.my_index == 0:
            transaction = CMutableTransaction([self.anchor], [self.our, self.their])
        elif self.anchor.scriptSig.my_index == 1:
            transaction = CMutableTransaction([self.anchor], [self.their, self.our])
        else:
            raise Exception("Unknown index", self.anchor.scriptSig.my_index)
        return CMutableTransaction.from_tx(transaction)

    def settlement_sig(self):
        """Generate a signature for the settlement transaction."""
        transaction = self.unsigned_settlement()
        transaction.vin[0].scriptSig = transaction.vin[0].scriptSig.to_script()
        for tx_out in transaction.vout:
            tx_out.scriptPubKey = tx_out.scriptPubKey.to_scriptPubKey()
        sighash = SignatureHash(self.anchor.scriptSig.redeem, transaction, 0, SIGHASH_ALL)
        sig = self.private_key.sign(sighash) + bytes([SIGHASH_ALL])
        return sig

    def signed_settlement(self, their_sig):
        """Return the fully signed settlement transaction."""
        transaction = self.unsigned_settlement()
        for tx_out in transaction.vout:
            tx_out.scriptPubKey = tx_out.scriptPubKey.to_scriptPubKey()
        sighash = SignatureHash(self.anchor.scriptSig.redeem, transaction, 0, SIGHASH_ALL)
        sig = self.private_key.sign(sighash) + bytes([SIGHASH_ALL])
        transaction.vin[0].scriptSig.sig = their_sig
        transaction.vin[0].scriptSig = transaction.vin[0].scriptSig.to_script(sig)
        VerifyScript(transaction.vin[0].scriptSig,
                     self.anchor.scriptSig.redeem.to_p2sh_scriptPubKey(),
                     transaction, 0, (SCRIPT_VERIFY_P2SH,))
        return transaction

    def handle(self, task):
        """Handle one task (input event for the state machine)."""
        name, args, kwargs = task
        self.table[name](self, *args, **kwargs)

    @table.add('pkt_error')
    def error(self, error_msg):
        """Deal with an error from counterparty."""
        raise Exception("Counterparty sent error: %s" % error_msg)

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
        self.state = 'open_wait_1.5'

    @table.add('pkt_open_accept')
    def open_accept(self, transaction, redeem, their_addr):
        """Counterparty accepted open."""
        assert self.state == 'open_wait_1'
        transaction = self.bitcoind.signrawtransaction(transaction)
        assert transaction['complete']
        transaction = transaction['tx']
        self.bitcoind.sendrawtransaction(transaction)
        self.their.scriptPubKey = their_addr
        self.anchor.scriptSig = AnchorScriptSig(1, b'', redeem)
        self.anchor.prevout = CMutableOutPoint(transaction.GetHash(), 0)
        self.bob.update_anchor(self.anchor.prevout.hash, self.sig_for_them())
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
        cmd_complete.send(self.cmd_id)
        self.cmd_id = None
        self.state = 'normal'

    @table.add('cmd_send')
    def send(self, cmd_id, amount):
        """Send amount satoshis."""
        assert self.state == 'normal'
        self.cmd_id = cmd_id
        self.bob.update(amount)
        self.state = 'send_wait_1'

    @table.add('pkt_update')
    def update(self, amount):
        """Return a signature for the update."""
        assert self.state == 'normal'
        assert amount >= 0
        self.our.nValue -= amount
        self.their.nValue += amount
        sig = self.sig_for_them()
        self.our.nValue += amount
        self.their.nValue -= amount
        self.bob.update_accept(amount, sig)
        self.state = 'send_wait_1.5'

    @table.add('pkt_update_accept')
    def update_accept(self, amount, sig):
        """Recieve a new signature from Bob."""
        assert self.state == 'send_wait_1'
        self.our.nValue -= amount
        self.their.nValue += amount
        self.anchor.scriptSig.sig = sig
        self.bob.update_signature(amount, self.sig_for_them())
        cmd_complete.send(self.cmd_id)
        self.cmd_id = None
        self.state = 'normal'

    @table.add('pkt_update_signature')
    def update_signature(self, amount, sig):
        """Recieve a new signature."""
        assert self.state == 'send_wait_1.5'
        assert amount >= 0
        self.our.nValue += amount
        self.their.nValue -= amount
        self.anchor.scriptSig.sig = sig
        self.state = 'normal'

    @table.add('cmd_close')
    def close_command(self, cmd_id):
        """Cooperatively close the channel."""
        assert self.state == 'normal'
        self.cmd_id = cmd_id
        self.bob.close(self.settlement_sig())
        self.state = 'close_wait_1'

    @table.add('pkt_close')
    def close_packet(self, sig):
        """Finish closing the channel."""
        assert self.state == 'normal'
        transaction = self.signed_settlement(sig)
        self.bitcoind.sendrawtransaction(transaction)
        self.bob.close_ack()
        self.state = 'end'

    @table.add('pkt_close_ack')
    def close_ack(self):
        """Confirm the close."""
        assert self.state == 'close_wait_1'
        cmd_complete.send(self.cmd_id)
        self.cmd_id = None
        self.state = 'end'

def task_handler(database, bitcoind_address, local_address):
    """Task handler thread main function."""
    logger.debug("Starting task handler.")
    logger.debug("bitcoind address: %s", bitcoind_address)
    Channel.bitcoind = bitcoin.rpc.Proxy(bitcoind_address)
    Channel.local_address = local_address
    try:
        root_key = database.Get(b'root_key')
    except KeyError:
        # TODO: grab a real private key from bitcoind
        root_key = CBitcoinSecret.from_secret_bytes(bytes(bitcoind_address, 'ascii'))
        database.Put(b'root_key', root_key)
    Channel.private_key = root_key
    while True:
        address, task = tasks.get()
        key = address.encode('utf-8')
        logger.debug("Task for %s: %r", address, task)
        try:
            channel = pickle.loads(database.Get(key))
        except KeyError:
            channel = Channel(address)
        try:
            channel.handle(task)
        except:
            logger.exception("Error handling task %s for %s", task, address)
            try:
                channel.bob.error("An unexpected error occured, I'm dying")
            finally:
                raise
        database.Put(key, pickle.dumps(channel))

API = Blueprint('channel', __name__, url_prefix='/channel')
@API.before_app_first_request
def set_up():
    """Start task_handler thread."""
    logger.debug("Call set_up")
    database = current_app.config['channel_database']
    bitcoind = current_app.config['bitcoind_address']
    port = int(current_app.config['port'])
    local_address = 'http://localhost:%d/' % port
    def run():
        """Run the task_handler."""
        try:
            task_handler(database, bitcoind, local_address)
        except BaseException:
            task_error.send('task_handler')
            raise
    task_thread = threading.Thread(target=run, daemon=True)
    task_thread.start()
    current_app.config['channel_task_thread'] = task_thread
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
            args = jsonrpcproxy.from_json(args)
            kwargs = jsonrpcproxy.from_json(kwargs)
            logger.debug("Queue pkt_%s from %s", key, address)
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
    logger.debug("Create %s %d %d", address, my_money, their_money)
    cmd_id = get_uid()
    complete_event = threading.Event()
    def complete(dummy_id, **dummy_args):
        """Unblock."""
        complete_event.set()
    cmd_complete.connect(complete, sender=cmd_id)
    task_error.connect(complete)
    tasks.put((address, ('cmd_open', (cmd_id, my_money, their_money), {})))
    complete_event.wait()
    if not current_app.config['channel_task_thread'].is_alive():
        raise Exception("Error creating channel")

def send(address, amount):
    """Send money."""
    logger.debug("Send %s %d", address, amount)
    cmd_id = get_uid()
    complete_event = threading.Event()
    def complete(dummy_id, **dummy_args):
        """Unblock."""
        complete_event.set()
    cmd_complete.connect(complete, sender=cmd_id)
    task_error.connect(complete)
    tasks.put((address, ('cmd_send', (cmd_id, amount), {})))
    complete_event.wait()
    if not current_app.config['channel_task_thread'].is_alive():
        raise Exception("Error sending money")

def close(address):
    """Close the channel."""
    logger.debug("Close %s", address)
    cmd_id = get_uid()
    complete_event = threading.Event()
    def complete(dummy_id, **dummy_args):
        """Unblock."""
        complete_event.set()
    cmd_complete.connect(complete, sender=cmd_id)
    task_error.connect(complete)
    tasks.put((address, ('cmd_close', (cmd_id,), {})))
    complete_event.wait()
    if not current_app.config['channel_task_thread'].is_alive():
        raise Exception("Error closing")

def getbalance(address):
    """Get a balance."""
    database = current_app.config['channel_database']
    key = address.encode('utf-8')
    channel = pickle.loads(database.Get(key))
    return channel.our.nValue

def getcommitmenttransactions(address):
    """Get the list of commitment transactions."""
    database = current_app.config['channel_database']
    key = address.encode('utf-8')
    channel = pickle.loads(database.Get(key))
    return [channel.signed_commitment(),]
