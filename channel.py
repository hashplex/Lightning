"""Micropayment channel API for a lightning node.

Interface:
API -- the Blueprint returned by serverutil.api_factory

CHANNEL_OPENED -- a blinker signal sent when a channel is opened.
Arguments:
- address -- the url of the counterparty

create(url, mymoney, theirmoney)
- Open a channel with the node identified by url,
  where you can send mymoney satoshis, and recieve theirmoney satoshis.
send(url, amount)
- Update a channel by sending amount satoshis to the node at url.
getbalance(url)
- Return the number of satoshis you can send in the channel with url.
close(url)
- Close the channel with url.
getcommitmenttransactions(url)
- Return a list of the commitment transactions in a payment channel

HTLC operation has not yet been defined.

Error conditions have not yet been defined.
"""

import os.path
import sqlite3
from flask import g
from blinker import Namespace
from bitcoin.core import COutPoint, CMutableTxOut, CMutableTxIn
from bitcoin.core import CMutableTransaction
from bitcoin.core.scripteval import VerifyScript, SCRIPT_VERIFY_P2SH
from bitcoin.core.scripteval import VerifyScriptError
from bitcoin.core.script import CScript, SignatureHash, SIGHASH_ALL
from bitcoin.core.script import OP_CHECKMULTISIG
import jsonrpcproxy
from serverutil import api_factory, requires_auth

API, REMOTE = api_factory('channel')

SIGNALS = Namespace()
CHANNEL_OPENED = SIGNALS.signal('CHANNEL_OPENED')

class AnchorScriptSig(object):
    """Class representing the scriptSig satisfying the anchor output"""
    def __init__(self, my_index, sig1, sig2, redeem):
        if my_index == b'':
            my_index = 0
        self.my_index = my_index
        if my_index == 0:
            self.my_sig, self.their_sig = sig1, sig2
        elif my_index == 1:
            self.my_sig, self.their_sig = sig2, sig1
        else:
            raise Exception("Unknown index", my_index)
        self.redeem = redeem

    @classmethod
    def from_script(cls, script):
        """Construct an AnchorScriptSig from a CScript."""
        script = list(script)
        assert len(script) == 4
        return cls(*script)

    def to_script(self):
        """Construct a CScript from an AnchorScriptSig."""
        if self.my_index == 0:
            sig1, sig2 = self.my_sig, self.their_sig
        elif self.my_index == 1:
            sig1, sig2 = self.their_sig, self.my_sig
        else:
            raise Exception("Unknown index", self.my_index)
        return CScript([self.my_index, sig1, sig2, self.redeem])

# This should really come from an ORM
class Channel(object):
    """Model of a payment channel."""
    address = None
    commitment = None
    def __init__(self):
        script_sig = AnchorScriptSig(0, b'', b'', b'').to_script()
        self.commitment = CMutableTransaction(
            [CMutableTxIn(scriptSig=script_sig)],
            [CMutableTxOut(), CMutableTxOut()])

    @staticmethod
    def create_table(dat):
        """Set up the backing table."""
        dat.execute("CREATE TABLE CHANNELS(address PRIMARY KEY, commitment)")

    @classmethod
    def get(cls, address):
        """Get a Channel with the specified address."""
        row = g.dat.execute(
            "SELECT * from CHANNELS WHERE address = ?", (address,)).fetchone()
        if row is None:
            raise Exception("Unknown address", address)
        self = cls()
        self.address, self.commitment = row
        self.commitment = CMutableTransaction.deserialize(self.commitment)
        self.commitment = CMutableTransaction.from_tx(self.commitment)
        return self

    def put(self):
        """Persist self."""
        with g.dat:
            g.dat.execute("INSERT OR REPLACE INTO CHANNELS VALUES (?, ?)",
                          (self.address, self.commitment.serialize()))

    def delete(self):
        """Delete self."""
        with g.dat:
            g.dat.execute("DELETE FROM CHANNELS WHERE address = ?",
                          (self.address,))

    @property
    def amount(self):
        """Get the amount of money you have in the channel."""
        return self.commitment.vout[0].nValue

    @amount.setter
    def amount(self, value):
        """Set the amount of money you have in the channel."""
        self.commitment.vout[0].nValue = value

    @property
    def redeem(self):
        """Get the redeem script."""
        return AnchorScriptSig.from_script(
            self.commitment.vin[0].scriptSig).redeem

    @redeem.setter
    def redeem(self, value):
        """Set the redeem script."""
        script = AnchorScriptSig.from_script(self.commitment.vin[0].scriptSig)
        script.redeem = value
        self.commitment.vin[0].scriptSig = script.to_script()

    @property
    def anchor(self):
        """Get the anchor txid."""
        return self.commitment.vin[0].prevout.hash

    @anchor.setter
    def anchor(self, value):
        """Set the anchor txid."""
        self.commitment.vin[0].prevout.hash = value

def init(conf):
    """Set up the database."""
    conf['database_path'] = os.path.join(conf['datadir'], 'channel.dat')
    if not os.path.isfile(conf['database_path']):
        dat = sqlite3.connect(conf['database_path'])
        with dat:
            Channel.create_table(dat)

@API.before_app_request
def before_request():
    """Set up database connection."""
    g.dat = sqlite3.connect(g.config['database_path'])

@API.teardown_app_request
def teardown_request(dummyexception):
    """Close database connection."""
    dat = getattr(g, 'dat', None)
    if dat is not None:
        g.dat.close()

@API.route('/dump')
@requires_auth
def dump():
    """Dump the DB."""
    return '\n'.join(line for line in g.dat.iterdump())

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

def update_db(address, amount):
    """Update the db for a payment."""
    channel = Channel.get(address)
    channel.amount += amount
    channel.put()

def create(url, mymoney, theirmoney, fees=10000):
    """Open a payment channel.

    After this method returns, a payment channel will have been established
    with the node identified by url, in which you can send mymoney satoshis
    and recieve theirmoney satoshis. Any blockchain fees involved in the
    setup and teardown of the channel should be collected at this time.
    """
    bob = jsonrpcproxy.Proxy(url+'channel/')
    coins, change = select_coins(mymoney + 2 * fees)
    pubkey = get_pubkey()
    transaction, redeem = bob.open_channel(
        g.addr, theirmoney, mymoney, fees,
        coins, change,
        pubkey)
    transaction = transaction
    anchor_output_script = redeem
    transaction = g.bit.signrawtransaction(transaction)
    assert transaction['complete']
    transaction = transaction['tx']
    g.bit.sendrawtransaction(transaction)
    channel = Channel()
    channel.address = url
    channel.amount = mymoney
    channel.anchor = transaction.GetHash()
    channel.redeem = anchor_output_script
    channel.put()
    bob.update_anchor(g.addr, transaction.GetHash())
    CHANNEL_OPENED.send('channel', address=url)

def send(url, amount):
    """Send coin in the channel.

    Negotiate the update of the channel opened with node url paying that node
    amount more satoshis than before. No fees should be collected by this
    method.
    """
    update_db(url, -amount)
    bob = jsonrpcproxy.Proxy(url+'channel/')
    bob.recieve(g.addr, amount)

def getbalance(url):
    """Get the balance of funds in a payment channel.

    This returns the number of satoshis you can spend in the channel
    with the node at url. This should have no side effects.
    """
    return Channel.get(url).amount

def getcommitmenttransactions(dummy_url):
    """Get the current commitment transactions in a payment channel."""
    return []

def close(url):
    """Close a channel.

    Close the currently open channel with node url. Any funds in the channel
    are paid to the wallet, along with any fees collected by create which
    were unnecessary."""
    bob = jsonrpcproxy.Proxy(url+'channel/')
    channel = Channel.get(url)
    redeem = CScript(channel.redeem)
    output = CMutableTxOut(
        channel.amount, g.bit.getnewaddress().to_scriptPubKey())
    transaction, bob_sig = bob.close_channel(g.addr, output)
    transaction = transaction
    anchor = transaction.vin[0]
    bob_sig = bob_sig
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
    channel.delete()

@REMOTE
def info():
    """Get bitcoind info."""
    return g.bit.getinfo()

@REMOTE
def get_address():
    """Get payment address."""
    return str(g.bit.getnewaddress())

@REMOTE
def open_channel(address, mymoney, theirmoney, fees, their_coins, their_change, their_pubkey): # pylint: disable=too-many-arguments
    """Open a payment channel."""
    coins, change = select_coins(mymoney + 2 * fees)
    anchor_output_script = anchor_script(get_pubkey(), their_pubkey)
    anchor_output_address = anchor_output_script.to_p2sh_scriptPubKey()
    payment = CMutableTxOut(mymoney + theirmoney + 2 * fees, anchor_output_address)
    transaction = CMutableTransaction(
        their_coins + coins,
        [payment, change, their_change])
    transaction = g.bit.signrawtransaction(transaction)
    transaction = transaction['tx']
    channel = Channel()
    channel.address = address
    channel.amount = mymoney
    channel.anchor = transaction.GetHash()
    channel.redeem = anchor_output_script
    channel.put()
    CHANNEL_OPENED.send('channel', address=address)
    return (transaction, anchor_output_script)

@REMOTE
def update_anchor(address, new_anchor):
    """Update the anchor txid after both have signed."""
    channel = Channel.get(address)
    channel.anchor = new_anchor
    channel.put()

@REMOTE
def recieve(address, amount):
    """Recieve money."""
    update_db(address, amount)

@REMOTE
def close_channel(address, their_output):
    """Close a channel."""
    channel = Channel.get(address)
    anchor = channel.anchor
    redeem = CScript(channel.redeem)
    output = CMutableTxOut(
        channel.amount, g.bit.getnewaddress().to_scriptPubKey())
    anchor = CMutableTxIn(COutPoint(anchor, 0))
    transaction = CMutableTransaction([anchor,], [output, their_output])
    sighash = SignatureHash(redeem, transaction, 0, SIGHASH_ALL)
    sig = g.seckey.sign(sighash) + bytes([SIGHASH_ALL])
    channel.delete()
    return (transaction, sig)
