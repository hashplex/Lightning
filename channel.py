"""Micropayment API for a lightning node."""

import jsonrpcproxy
from jsonrpc.backend.flask import JSONRPCAPI
from flask import g, Blueprint, current_app
from bitcoin.core import COutPoint, CMutableTxOut, CMutableTxIn
from bitcoin.core import CMutableTransaction
from bitcoin.core.scripteval import VerifyScript, SCRIPT_VERIFY_P2SH
from bitcoin.core.scripteval import VerifyScriptError
from bitcoin.core.script import CScript, SignatureHash, SIGHASH_ALL
from bitcoin.core.script import OP_CHECKMULTISIG
from base64 import b64encode, b64decode
from bitcoin.core.serialize import Serializable
from bitcoin.wallet import CBitcoinSecret
import sqlite3
import hashlib
import os.path
from blinker import Namespace

API = Blueprint('channel', __name__)
RPC_API = JSONRPCAPI()
REMOTE = RPC_API.dispatcher.add_method
API.add_url_rule('/', 'rpc', RPC_API.as_view(), methods=['POST'])

SIGNALS = Namespace()
CHANNEL_OPENED = SIGNALS.signal('CHANNEL_OPENED')

def init(conf):
    """Set up the database."""
    conf['database_path'] = os.path.join(conf['datadir'], 'channel.dat')
    if not os.path.isfile(conf['database_path']):
        dat = sqlite3.connect(conf['database_path'])
        with dat:
            dat.execute("CREATE TABLE CHANNELS(address, amount, anchor, fees, redeem)")

def before_request():
    """Set up g context."""
    g.config = current_app.config
    g.bit = g.config['bitcoind']
    g.dat = sqlite3.connect(g.config['database_path'])
    secret = hashlib.sha256(g.config['secret']).digest()
    g.seckey = CBitcoinSecret.from_secret_bytes(secret)
    g.addr = 'http://localhost:%d/' % int(g.config['port'])

def teardown_request(dummyexception):
    """Clean up."""
    dat = getattr(g, 'dat', None)
    if dat is not None:
        g.dat.close()

@API.route('/dump')
def dump():
    """Dump the DB."""
    return '\n'.join(line for line in g.dat.iterdump())

IDENTITY = lambda arg: arg

def serialize_bytes(bytedata):
    """Convert bytes to str."""
    return b64encode(bytedata).decode()

def deserialize_bytes(b64data):
    """Convert str to bytes."""
    return b64decode(b64data.encode())

class Message(object):
    """Base class for JSON serializable messages."""
    fields = []
    def __init__(self, **kwargs):
        for arg in kwargs:
            setattr(self, arg, kwargs[arg])

    def json(self):
        """Convert message to JSON."""
        return {
            field: to_json(field_type, getattr(self, field))
            for field, field_type in self.fields
        }

    @classmethod
    def from_json(cls, json_data):
        """Convert message from JSON."""
        self = cls()
        for field, field_type in cls.fields:
            setattr(self, field, from_json(field_type, json_data[field]))
        return self

RAW_JSON_TYPES = [int, str,]
def to_json(message, field_type=None):
    """Convert a message to JSON"""
    if isinstance(message, list):
        return [to_json(sub, field_type) for sub in message]
    if field_type == None:
        field_type = type(message)
    if field_type in RAW_JSON_TYPES:
        return message
    if issubclass(field_type, bytes):
        return serialize_bytes(message)
    if issubclass(field_type, Serializable):
        return to_json(message.serialize(), bytes)
    if issubclass(field_type, Message):
        return message.json()
    raise Exception("Unable to convert", field_type, message)
def from_json(message, field_type):
    """Convert a message from JSON"""
    if isinstance(message, list):
        return [from_json(sub, field_type) for sub in message]
    if field_type in RAW_JSON_TYPES:
        return message
    if issubclass(field_type, bytes):
        return field_type(deserialize_bytes(message))
    if issubclass(field_type, Serializable):
        return field_type.deserialize(from_json(message, bytes))
    if issubclass(field_type, Message):
        return field_type.from_json(message)
    raise Exception("Unable to convert", field_type, message)

class CreationMessage(Message):
    """Sent when a channel is opened."""
    fields = [
        ('my_money', int),
        ('your_money', int),
        ('fees', int),
        ('my_coins', CMutableTxIn),
        ('my_change', CMutableTxOut),
        ('my_pubkey', bytes),
    ]

def select_coins(amount):
    """Get a txin set and change to spend amount."""
    coins = g.bit.listunspent()
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
        -amount, g.bit.getrawchangeaddress().to_scriptPubKey())
    return out, change

def anchor_script(my_pubkey, their_pubkey):
    """Generate the output script for the anchor transaction."""
    script = CScript([2, my_pubkey, their_pubkey, 2, OP_CHECKMULTISIG])
    return script

def get_pubkey():
    """Get a new pubkey."""
    return g.seckey.pub

def create(url, mymoney, theirmoney, fees):
    """Open a payment channel."""
    bob = jsonrpcproxy.Proxy(url+'channel/')
    coins, change = select_coins(mymoney + 2 * fees)
    pubkey = get_pubkey()
    transaction, redeem = bob.open_channel(
        g.addr, theirmoney, mymoney, fees,
        to_json(coins), to_json(change),
        to_json(pubkey))
    transaction = CMutableTransaction.deserialize(deserialize_bytes(
        transaction))
    anchor_output_script = CScript(deserialize_bytes(redeem))
    transaction = g.bit.signrawtransaction(transaction)
    assert transaction['complete']
    transaction = transaction['tx']
    g.bit.sendrawtransaction(transaction)
    with g.dat:
        g.dat.execute(
            "INSERT INTO CHANNELS(address, amount, anchor, fees, redeem) VALUES (?, ?, ?, ?, ?)",
            (url, mymoney, transaction.GetHash(), fees, anchor_output_script))
    bob.update_anchor(g.addr, to_json(transaction.GetHash()))
    CHANNEL_OPENED.send('channel', address=url, fees=fees)
    return True

def lightning_balance():
    """Get the balance in lightning channels exclusively."""
    return sum(
        row[0]
        for row in g.dat.execute("SELECT amount, fees FROM CHANNELS")
        )

def update_db(address, amount):
    """Update the db for a payment."""
    row = g.dat.execute(
        "SELECT address, amount from CHANNELS WHERE address = ?", (address,)
    ).fetchone()
    if row is None:
        raise Exception("Unknown address", address)
    address, current_amount = row
    with g.dat:
        g.dat.execute(
            "UPDATE CHANNELS SET amount = ? WHERE address = ?", (current_amount + amount, address))

def getbalance():
    """Get the balance including funds locked in payment channels."""
    return lightning_balance() + g.bit.getbalance()

def send(url, amount):
    """Send coin in the channel."""
    update_db(url, -amount)
    bob = jsonrpcproxy.Proxy(url+'channel/')
    bob.recieve(g.addr, amount)
    return True

def close(url):
    """Close a channel."""
    bob = jsonrpcproxy.Proxy(url+'channel/')
    row = g.dat.execute("SELECT * from CHANNELS WHERE address = ?", (url,)).fetchone()
    if row is None:
        raise Exception("Unknown address", url)
    address, current_amount, anchor, fees, redeem = row
    redeem = CScript(redeem)
    output = CMutableTxOut(
        current_amount, g.bit.getnewaddress().to_scriptPubKey())
    serialized_output = serialize_bytes(output.serialize())
    transaction, bob_sig = bob.close_channel(g.addr, serialized_output)
    transaction = CMutableTransaction.deserialize(deserialize_bytes(
        transaction))
    transaction = CMutableTransaction.from_tx(transaction)
    anchor = transaction.vin[0]
    bob_sig = deserialize_bytes(bob_sig)
    sighash = SignatureHash(redeem, transaction, 0, SIGHASH_ALL)
    sig = g.seckey.sign(sighash) + bytes([SIGHASH_ALL])
    anchor.scriptSig = CScript([0, bob_sig, sig, redeem])
    try:
        VerifyScript(anchor.scriptSig, redeem.to_p2sh_scriptPubKey(),
                     transaction, 0, (SCRIPT_VERIFY_P2SH,))
    except VerifyScriptError:
        anchor.scriptSig = CScript([0, sig, bob_sig, redeem])
        VerifyScript(anchor.scriptSig, redeem.to_p2sh_scriptPubKey(),
                     transaction, 0, (SCRIPT_VERIFY_P2SH,))
    g.bit.sendrawtransaction(transaction)
    with g.dat:
        g.dat.execute("DELETE FROM CHANNELS WHERE address = ?", (url,))
    return True

@REMOTE
def info():
    """Get bitcoind info."""
    return g.bit.getinfo()

@REMOTE
def get_address():
    """Get payment address."""
    return str(g.bit.getnewaddress())

@REMOTE
def open_channel(address, mymoney, theirmoney, fees, their_coins, their_change,
                 their_pubkey):
    """Open a payment channel."""
    their_coins = from_json(their_coins, CMutableTxIn)
    their_change = from_json(their_change, CMutableTxOut)
    their_pubkey = from_json(their_pubkey, bytes)
    coins, change = select_coins(mymoney + 2 * fees)
    anchor_output_script = anchor_script(get_pubkey(), their_pubkey)
    anchor_output_address = anchor_output_script.to_p2sh_scriptPubKey()
    payment = CMutableTxOut(mymoney + theirmoney + 2 * fees, anchor_output_address)
    transaction = CMutableTransaction(
        their_coins + coins,
        [payment, change, their_change])
    transaction = g.bit.signrawtransaction(transaction)
    transaction = transaction['tx']
    with g.dat:
        g.dat.execute(
            "INSERT INTO CHANNELS(address, amount, anchor, fees, redeem) VALUES (?, ?, ?, ?, ?)",
            (address, mymoney, transaction.GetHash(), fees, anchor_output_script))
    CHANNEL_OPENED.send('channel', address=address, fees=fees)
    return (serialize_bytes(transaction.serialize()),
            serialize_bytes(anchor_output_script))

@REMOTE
def update_anchor(address, new_anchor):
    """Update the anchor txid after both have signed."""
    new_anchor = from_json(new_anchor, bytes)
    with g.dat:
        g.dat.execute("UPDATE CHANNELS SET anchor = ? WHERE address = ?", (new_anchor, address))
    return True

@REMOTE
def recieve(address, amount):
    """Recieve money."""
    update_db(address, amount)
    return True

@REMOTE
def close_channel(address, their_output):
    """Close a channel."""
    their_output = CMutableTxOut.deserialize(deserialize_bytes(their_output))
    row = g.dat.execute("SELECT * from CHANNELS WHERE address = ?", (address,)).fetchone()
    if row is None:
        raise Exception("Unknown address", address)
    address, current_amount, anchor, fees, redeem = row
    redeem = CScript(redeem)
    output = CMutableTxOut(
        current_amount, g.bit.getnewaddress().to_scriptPubKey())
    anchor = CMutableTxIn(COutPoint(anchor, 0))
    transaction = CMutableTransaction([anchor,], [output, their_output])
    sighash = SignatureHash(redeem, transaction, 0, SIGHASH_ALL)
    sig = g.seckey.sign(sighash) + bytes([SIGHASH_ALL])
    with g.dat:
        g.dat.execute("DELETE FROM CHANNELS WHERE address = ?", (address,))
    return (serialize_bytes(transaction.serialize()),
            serialize_bytes(sig))
