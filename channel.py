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

Database:
The schema is currently one row for each channel in table CHANNELS.
address: url for the counterpary
commitment: your commitment transaction
"""

import os.path
import sqlite3
from flask import g
from blinker import Namespace
from bitcoin.core import CMutableOutPoint, CMutableTxOut, CMutableTxIn
from bitcoin.core import CMutableTransaction
from bitcoin.core.scripteval import VerifyScript, SCRIPT_VERIFY_P2SH
from bitcoin.core.scripteval import VerifyScriptError
from bitcoin.core.script import CScript, SignatureHash, SIGHASH_ALL
from bitcoin.core.script import OP_CHECKMULTISIG, OP_PUBKEY
import jsonrpcproxy
from serverutil import api_factory, requires_auth

API, REMOTE = api_factory('channel')

SIGNALS = Namespace()
CHANNEL_OPENED = SIGNALS.signal('CHANNEL_OPENED')

class AnchorScriptSig(object):
    """Class representing the scriptSig satisfying the anchor output"""
    def __init__(self, my_index, sig=b'', redeem=b''):
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

# This should really come from an ORM
class Channel(object):
    """Model of a payment channel."""
    address = None
    commitment = None
    def __init__(self, my_index=0):
        script_sig = AnchorScriptSig(my_index).to_script()
        self.commitment = CMutableTransaction(
            [CMutableTxIn(prevout=CMutableOutPoint(n=0),
                          scriptSig=script_sig)],
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
    def their_amount(self):
        """Get the amount of money they have in the channel."""
        return self.commitment.vout[1].nValue

    @their_amount.setter
    def their_amount(self, value):
        """Set the amount of money they have in the channel."""
        self.commitment.vout[1].nValue = value

    @property
    def redeem(self):
        """Get the redeem script."""
        return self.get_script_sig().redeem

    @redeem.setter
    def redeem(self, value):
        """Set the redeem script."""
        script = self.get_script_sig()
        script.redeem = value
        self.set_script_sig(script)

    @property
    def anchor(self):
        """Get the anchor txid."""
        return self.commitment.vin[0].prevout.hash

    @anchor.setter
    def anchor(self, value):
        """Set the anchor txid."""
        self.commitment.vin[0].prevout.hash = value

    def get_script_sig(self):
        """Get the scriptSig for the anchor input."""
        return AnchorScriptSig.from_script(self.commitment.vin[0].scriptSig)

    def set_script_sig(self, value):
        """Set the scriptSig for the anchor input."""
        self.commitment.vin[0].scriptSig = value.to_script()

    @property
    def their_sig(self):
        """Get their signature."""
        return self.get_script_sig().sig

    @their_sig.setter
    def their_sig(self, value):
        """Set their signature."""
        script = self.get_script_sig()
        script.sig = value
        self.set_script_sig(script)

    @property
    def sig_for_them(self):
        """Generate a signature for the mirror commitment transaction."""
        transaction = CMutableTransaction.from_tx(self.commitment)
        transaction.vout.reverse()
        sighash = SignatureHash(self.redeem, transaction, 0, SIGHASH_ALL)
        sig = g.seckey.sign(sighash) + bytes([SIGHASH_ALL])
        return sig

    @property
    def signed_commitment(self):
        """Return the fully signed commitment transaction."""
        script = self.get_script_sig()
        transaction = CMutableTransaction.from_tx(self.commitment)
        sighash = SignatureHash(self.redeem, transaction, 0, SIGHASH_ALL)
        sig = g.seckey.sign(sighash) + bytes([SIGHASH_ALL])
        script = script.to_script(sig)
        transaction.vin[0].scriptSig = script
        VerifyScript(script, self.redeem.to_p2sh_scriptPubKey(),
                     transaction, 0, (SCRIPT_VERIFY_P2SH,))
        return transaction

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

def update_db(address, amount, sig):
    """Update the db for a payment."""
    channel = Channel.get(address)
    channel.amount += amount
    channel.their_amount -= amount
    channel.their_sig = sig
    channel.put()
    return channel.sig_for_them

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
    channel = Channel(1)
    channel.address = url
    channel.amount = mymoney
    channel.their_amount = theirmoney
    channel.anchor = transaction.GetHash()
    channel.redeem = anchor_output_script
    channel.put()
    channel.their_sig = bob.update_anchor(g.addr, transaction.GetHash(), channel.sig_for_them)
    CHANNEL_OPENED.send('channel', address=url)

def send(url, amount):
    """Send coin in the channel.

    Negotiate the update of the channel opened with node url paying that node
    amount more satoshis than before. No fees should be collected by this
    method.
    """
    bob = jsonrpcproxy.Proxy(url+'channel/')
    sig = update_db(url, -amount, bob.propose_update(g.addr, amount))
    bob.recieve(g.addr, amount, sig)

def getbalance(url):
    """Get the balance of funds in a payment channel.

    This returns the number of satoshis you can spend in the channel
    with the node at url. This should have no side effects.
    """
    return Channel.get(url).amount

def getcommitmenttransactions(url):
    """Get the current commitment transactions in a payment channel."""
    channel = Channel.get(url)
    commitment = channel.signed_commitment
    return [commitment,]

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
    channel = Channel(0)
    channel.address = address
    channel.amount = mymoney
    channel.their_amount = theirmoney
    channel.anchor = transaction.GetHash()
    channel.redeem = anchor_output_script
    channel.put()
    CHANNEL_OPENED.send('channel', address=address)
    return (transaction, anchor_output_script)

@REMOTE
def update_anchor(address, new_anchor, their_sig):
    """Update the anchor txid after both have signed."""
    channel = Channel.get(address)
    channel.anchor = new_anchor
    channel.their_sig = their_sig
    channel.put()
    return channel.sig_for_them

@REMOTE
def propose_update(address, amount):
    """Sign commitment transactions."""
    channel = Channel.get(address)
    assert amount > 0
    channel.amount += amount
    # don't persist yet
    return channel.sig_for_them

@REMOTE
def recieve(address, amount, sig):
    """Recieve money."""
    update_db(address, amount, sig)

@REMOTE
def close_channel(address, their_output):
    """Close a channel."""
    channel = Channel.get(address)
    anchor = channel.anchor
    redeem = CScript(channel.redeem)
    output = CMutableTxOut(
        channel.amount, g.bit.getnewaddress().to_scriptPubKey())
    anchor = CMutableTxIn(CMutableOutPoint(anchor, 0))
    transaction = CMutableTransaction([anchor,], [output, their_output])
    sighash = SignatureHash(redeem, transaction, 0, SIGHASH_ALL)
    sig = g.seckey.sign(sighash) + bytes([SIGHASH_ALL])
    channel.delete()
    return (transaction, sig)
