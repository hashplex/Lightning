"""Micropayment channel API for a lightning node.

Interface:
API -- the Blueprint returned by serverutil.api_factory

CHANNEL_OPENED -- a blinker signal sent when a channel is opened.
Arguments:
- address -- the url of the counterparty

init(conf) - Set up the database
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
from bitcoin.core.script import CScript, SignatureHash, SIGHASH_ALL
from bitcoin.core.script import OP_CHECKMULTISIG, OP_PUBKEY
from bitcoin.wallet import CBitcoinAddress
import jsonrpcproxy
from serverutil import api_factory, requires_auth

API, REMOTE, Model = api_factory('channel')

SIGNALS = Namespace()
CHANNEL_OPENED = SIGNALS.signal('CHANNEL_OPENED')

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

# This should really come from an ORM
class Channel(object):
    """Model of a payment channel.

    address - counterparty's url
    anchor - CMutableTxIn representing the spend from the anchor
    anchor.scriptSig is an instance of AnchorScriptSig
    our, their - CMutableTxOut representing the negotiated outputs.
                 Uses CBitcoinAddress for scriptPubKey.
    """

    address = None
    commitment = None

    def __init__(self, address, anchor, our, their):
        self.address = address
        self.anchor = anchor
        self.our = our
        self.their = their

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
        address, commitment = row
        commitment = CMutableTransaction.deserialize(commitment)
        commitment = CMutableTransaction.from_tx(commitment)
        assert len(commitment.vin) == 1
        assert len(commitment.vout) == 2
        commitment.vin[0].scriptSig = AnchorScriptSig.from_script(
            commitment.vin[0].scriptSig)
        for tx_out in commitment.vout:
            tx_out.scriptPubKey = CBitcoinAddress.from_scriptPubKey(tx_out.scriptPubKey)
        return cls(address,
                   commitment.vin[0],
                   commitment.vout[0],
                   commitment.vout[1])

    def put(self):
        """Persist self."""
        commitment = CMutableTransaction([self.anchor], [self.our, self.their])
        commitment = CMutableTransaction.from_tx(commitment)
        commitment.vin[0].scriptSig = commitment.vin[0].scriptSig.to_script()
        for tx_out in commitment.vout:
            tx_out.scriptPubKey = tx_out.scriptPubKey.to_scriptPubKey()
        with g.dat:
            g.dat.execute("INSERT OR REPLACE INTO CHANNELS VALUES (?, ?)",
                          (self.address, commitment.serialize()))

    def delete(self):
        """Delete self."""
        with g.dat:
            g.dat.execute("DELETE FROM CHANNELS WHERE address = ?",
                          (self.address,))

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
        sig = g.seckey.sign(sighash) + bytes([SIGHASH_ALL])
        return sig

    def signed_commitment(self):
        """Return the fully signed commitment transaction."""
        transaction = CMutableTransaction([self.anchor], [self.our, self.their])
        transaction = CMutableTransaction.from_tx(transaction)
        for tx_out in transaction.vout:
            tx_out.scriptPubKey = tx_out.scriptPubKey.to_scriptPubKey()
        sighash = SignatureHash(self.anchor.scriptSig.redeem, transaction, 0, SIGHASH_ALL)
        sig = g.seckey.sign(sighash) + bytes([SIGHASH_ALL])
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
        sig = g.seckey.sign(sighash) + bytes([SIGHASH_ALL])
        return sig

    def signed_settlement(self, their_sig):
        """Return the fully signed settlement transaction."""
        transaction = self.unsigned_settlement()
        for tx_out in transaction.vout:
            tx_out.scriptPubKey = tx_out.scriptPubKey.to_scriptPubKey()
        sighash = SignatureHash(self.anchor.scriptSig.redeem, transaction, 0, SIGHASH_ALL)
        sig = g.seckey.sign(sighash) + bytes([SIGHASH_ALL])
        transaction.vin[0].scriptSig.sig = their_sig
        transaction.vin[0].scriptSig = transaction.vin[0].scriptSig.to_script(sig)
        VerifyScript(transaction.vin[0].scriptSig,
                     self.anchor.scriptSig.redeem.to_p2sh_scriptPubKey(),
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
    channel.our.nValue += amount
    channel.their.nValue -= amount
    channel.anchor.scriptSig.sig = sig
    channel.put()
    return channel.sig_for_them()

def create(url, mymoney, theirmoney, fees=10000):
    """Open a payment channel.

    After this method returns, a payment channel will have been established
    with the node identified by url, in which you can send mymoney satoshis
    and recieve theirmoney satoshis. Any blockchain fees involved in the
    setup and teardown of the channel should be collected at this time.
    """
    bob = jsonrpcproxy.Proxy(url+'channel/')
    # Choose inputs and change output
    coins, change = select_coins(mymoney + 2 * fees)
    pubkey = get_pubkey()
    my_out_addr = g.bit.getnewaddress()
    # Tell Bob we want to open a channel
    transaction, redeem, their_out_addr = bob.open_channel(
        g.addr, theirmoney, mymoney, fees,
        coins, change,
        pubkey, my_out_addr)
    # Sign and send the anchor
    transaction = g.bit.signrawtransaction(transaction)
    assert transaction['complete']
    transaction = transaction['tx']
    g.bit.sendrawtransaction(transaction)
    # Set up the channel in the DB
    channel = Channel(url,
                      CMutableTxIn(CMutableOutPoint(transaction.GetHash(), 0),
                                   AnchorScriptSig(1, b'', redeem)),
                      CMutableTxOut(mymoney, my_out_addr),
                      CMutableTxOut(theirmoney, their_out_addr))
    # Exchange signatures for the inital commitment transaction
    channel.anchor.scriptSig.sig = \
        bob.update_anchor(g.addr, transaction.GetHash(), channel.sig_for_them())
    channel.put()
    # Event: channel opened
    CHANNEL_OPENED.send('channel', address=url)

def send(url, amount):
    """Send coin in the channel.

    Negotiate the update of the channel opened with node url paying that node
    amount more satoshis than before. No fees should be collected by this
    method.
    """
    bob = jsonrpcproxy.Proxy(url+'channel/')
    # ask Bob to sign the new commitment transactions, and update.
    sig = update_db(url, -amount, bob.propose_update(g.addr, amount))
    # tell Bob our signature
    bob.recieve(g.addr, amount, sig)

def getbalance(url):
    """Get the balance of funds in a payment channel.

    This returns the number of satoshis you can spend in the channel
    with the node at url. This should have no side effects.
    """
    return Channel.get(url).our.nValue

def getcommitmenttransactions(url):
    """Get the current commitment transactions in a payment channel."""
    channel = Channel.get(url)
    commitment = channel.signed_commitment()
    return [commitment,]

def close(url):
    """Close a channel.

    Close the currently open channel with node url. Any funds in the channel
    are paid to the wallet, along with any fees collected by create which
    were unnecessary."""
    bob = jsonrpcproxy.Proxy(url+'channel/')
    channel = Channel.get(url)
    # Tell Bob we are closing the channel, and sign the settlement tx
    bob.close_channel(g.addr, channel.settlement_sig())
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
def open_channel(address, mymoney, theirmoney, fees, their_coins, their_change, their_pubkey, their_out_addr): # pylint: disable=too-many-arguments, line-too-long
    """Open a payment channel."""
    # Get inputs and change output
    coins, change = select_coins(mymoney + 2 * fees)
    # Make the anchor script
    anchor_output_script = anchor_script(get_pubkey(), their_pubkey)
    anchor_output_address = anchor_output_script.to_p2sh_scriptPubKey()
    # Construct the anchor utxo
    payment = CMutableTxOut(mymoney + theirmoney + 2 * fees, anchor_output_address)
    # Anchor tx
    transaction = CMutableTransaction(
        their_coins + coins,
        [payment, change, their_change])
    # Half-sign
    transaction = g.bit.signrawtransaction(transaction)['tx']
    # Create channel in DB
    channel = Channel(address,
                      CMutableTxIn(CMutableOutPoint(transaction.GetHash(), 0),
                                   AnchorScriptSig(0, b'', anchor_output_script)),
                      CMutableTxOut(mymoney, g.bit.getnewaddress()),
                      CMutableTxOut(theirmoney, their_out_addr))
    channel.put()
    # Event: channel opened
    CHANNEL_OPENED.send('channel', address=address)
    return (transaction, anchor_output_script, channel.our.scriptPubKey)

@REMOTE
def update_anchor(address, new_anchor, their_sig):
    """Update the anchor txid after both have signed."""
    channel = Channel.get(address)
    channel.anchor.prevout.hash = new_anchor
    channel.anchor.scriptSig.sig = their_sig
    channel.put()
    return channel.sig_for_them()

@REMOTE
def propose_update(address, amount):
    """Sign commitment transactions."""
    channel = Channel.get(address)
    assert amount > 0
    channel.our.nValue += amount
    channel.their.nValue -= amount
    # don't persist yet
    return channel.sig_for_them()

@REMOTE
def recieve(address, amount, sig):
    """Recieve money."""
    update_db(address, amount, sig)

@REMOTE
def close_channel(address, their_sig):
    """Close a channel."""
    channel = Channel.get(address)
    # Sign and send settlement tx
    my_sig = channel.settlement_sig()
    transaction = channel.signed_settlement(their_sig)
    g.bit.sendrawtransaction(transaction)
    channel.delete()
    return my_sig
