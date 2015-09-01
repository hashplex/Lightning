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

from sqlalchemy import Column, Integer, String, LargeBinary
from flask import g
from blinker import Namespace
from bitcoin.core import COutPoint, CMutableTxOut, CMutableTxIn
from bitcoin.core import CMutableTransaction
from bitcoin.core.scripteval import VerifyScript, SCRIPT_VERIFY_P2SH
from bitcoin.core.script import CScript, SignatureHash, SIGHASH_ALL
from bitcoin.core.script import OP_CHECKMULTISIG, OP_PUBKEY
from bitcoin.wallet import CBitcoinAddress
import jsonrpcproxy
from serverutil import api_factory
from serverutil import database
from serverutil import ImmutableSerializableType, Base58DataType

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

class Channel(Model):
    """Model of a payment channel."""

    __tablename__ = 'channels'

    address = Column(String, primary_key=True)
    anchor_point = Column(ImmutableSerializableType(COutPoint),
                          unique=True, index=True)
    anchor_index = Column(Integer)
    their_sig = Column(LargeBinary)
    anchor_redeem = Column(LargeBinary)
    our_balance = Column(Integer)
    our_addr = Column(Base58DataType(CBitcoinAddress))
    their_balance = Column(Integer)
    their_addr = Column(Base58DataType(CBitcoinAddress))

    def signature(self, transaction):
        """Signature for a transaction."""
        sighash = SignatureHash(CScript(self.anchor_redeem),
                                transaction, 0, SIGHASH_ALL)
        sig = g.seckey.sign(sighash) + bytes([SIGHASH_ALL])
        return sig

    def sign(self, transaction):
        """Sign a transaction."""
        sig = self.signature(transaction)
        anchor_sig = AnchorScriptSig(self.anchor_index,
                                     self.their_sig,
                                     self.anchor_redeem)
        transaction.vin[0].scriptSig = anchor_sig.to_script(sig)
        # verify signing worked
        VerifyScript(transaction.vin[0].scriptSig,
                     CScript(self.anchor_redeem).to_p2sh_scriptPubKey(),
                     transaction, 0, (SCRIPT_VERIFY_P2SH,))
        return transaction

    def commitment(self, ours=False):
        """Return an unsigned commitment transaction."""
        first = CMutableTxOut(self.our_balance, self.our_addr.to_scriptPubKey())
        second = CMutableTxOut(self.their_balance, self.their_addr.to_scriptPubKey())
        if not ours:
            first, second = second, first
        return CMutableTransaction([CMutableTxIn(self.anchor_point)],
                                   [first, second])

    def settlement(self):
        """Generate the settlement transaction."""
        # Put outputs in the order of the inputs, so that both versions are the same
        first = CMutableTxOut(self.our_balance,
                              self.our_addr.to_scriptPubKey())
        second = CMutableTxOut(self.their_balance,
                               self.their_addr.to_scriptPubKey())
        if self.anchor_index == 0:
            pass
        elif self.anchor_index == 1:
            first, second = second, first
        else:
            raise Exception("Unknown index", self.anchor_index)
        return CMutableTransaction([CMutableTxIn(self.anchor_point)],
                                   [first, second])

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
    channel = Channel.query.get(address) # address is lightning address, address is primary key 
    
    # verify that signature is valid here 

    channel.our_balance += amount
    channel.their_balance -= amount
    channel.their_sig = sig
    database.session.commit()
    return channel.signature(channel.commitment()) # this is our signature of the comittment 

def create(url, mymoney, theirmoney, fees=10000):
    """Open a payment channel.

    After this method returns, a payment channel will have been established
    with the node identified by url, in which you can send mymoney satoshis
    and recieve theirmoney satoshis. Any blockchain fees involved in the
    setup and teardown of the channel should be collected at this time.
    """
    bob = jsonrpcproxy.Proxy(url+'channel/')
    # print ("bob: " + url + "channel/")
    # Choose inputs and change output
    coins, change = select_coins(mymoney + 2 * fees)
    # print ("coins: " + coins + ", change: ") 
    pubkey = get_pubkey()
    # print ("pubkey: " + pubkey)
    my_out_addr = g.bit.getnewaddress()
    # print ("my out (bitcoin adddress for money when we close the channel) addr: " + my_out_addr)
    # print ("g.addr (our lightning address: " + g.addr )
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
    channel = Channel(address=url,
                      anchor_point=COutPoint(transaction.GetHash(), 0),
                      anchor_index=1,
                      their_sig=b'',
                      anchor_redeem=redeem,
                      our_balance=mymoney,
                      our_addr=my_out_addr,
                      their_balance=theirmoney,
                      their_addr=their_out_addr,
                     )
    # Exchange signatures for the inital commitment transaction
    channel.their_sig = \
        bob.update_anchor(g.addr, transaction.GetHash(),
                          channel.signature(channel.commitment())) 
                          # channel.signature(channel.commitment()) is our signature for the comitment
                          # 
    database.session.add(channel)
    database.session.commit()
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
    return Channel.query.get(url).our_balance

def getcommitmenttransactions(url):
    """Get the current commitment transactions in a payment channel."""
    channel = Channel.query.get(url)
    commitment = channel.sign(channel.commitment(ours=True))
    return [commitment,]

def close(url):
    """Close a channel.

    Close the currently open channel with node url. Any funds in the channel
    are paid to the wallet, along with any fees collected by create which
    were unnecessary."""
    bob = jsonrpcproxy.Proxy(url+'channel/')
    channel = Channel.query.get(url)
    # Tell Bob we are closing the channel, and sign the settlement tx
    bob.close_channel(g.addr, channel.signature(channel.settlement()))
    database.session.delete(channel)
    database.session.commit()

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
    # Construct the anchor utxo
    payment = CMutableTxOut(mymoney + theirmoney + 2 * fees,
                            anchor_output_script.to_p2sh_scriptPubKey())
    # Anchor tx
    transaction = CMutableTransaction(
        their_coins + coins,
        [payment, change, their_change])
    # Half-sign
    transaction = g.bit.signrawtransaction(transaction)['tx']
    # Create channel in DB
    our_addr = g.bit.getnewaddress()
    channel = Channel(address=address,
                      anchor_point=COutPoint(transaction.GetHash(), 0),
                      anchor_index=0,
                      their_sig=b'',
                      anchor_redeem=anchor_output_script,
                      our_balance=mymoney,
                      our_addr=our_addr,
                      their_balance=theirmoney,
                      their_addr=their_out_addr,
                     )
    database.session.add(channel)
    database.session.commit()
    # Event: channel opened
    CHANNEL_OPENED.send('channel', address=address)
    return (transaction, anchor_output_script, our_addr)

@REMOTE
def update_anchor(address, new_anchor, their_sig):
    """Update the anchor txid after both have signed."""
    channel = Channel.query.get(address)
    channel.anchor_point = COutPoint(new_anchor, channel.anchor_point.n)
    channel.their_sig = their_sig
    database.session.commit()
    return channel.signature(channel.commitment())

@REMOTE
def propose_update(address, amount):
    """Sign commitment transactions."""
    channel = Channel.query.get(address)
    assert amount > 0
    channel.our_balance += amount
    channel.their_balance -= amount
    # don't persist yet
    sig = channel.signature(channel.commitment())
    channel.our_balance -= amount
    channel.their_balance += amount
    return sig

@REMOTE
def recieve(address, amount, sig):
    """Recieve money."""
    update_db(address, amount, sig)

@REMOTE
def close_channel(address, their_sig):
    """Close a channel."""
    channel = Channel.query.get(address)
    # Sign and send settlement tx
    my_sig = channel.signature(channel.settlement())
    channel.their_sig = their_sig
    transaction = channel.sign(channel.settlement())
    g.bit.sendrawtransaction(transaction)
    database.session.delete(channel)
    database.session.commit()
    return my_sig
