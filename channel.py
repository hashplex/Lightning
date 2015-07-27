"""Private (local) API for a lightning node."""

import jsonrpcproxy
from jsonrpc.backend.flask import JSONRPCAPI
from flask import g
import bitcoin
import bitcoin.wallet
from bitcoin.core import b2x, lx, COIN
from bitcoin.core import COutPoint, CMutableTxOut, CMutableTxIn
from bitcoin.core import CMutableTransaction, Hash160
from bitcoin.wallet import CBitcoinAddress
from bitcoin.core.scripteval import VerifyScript, SCRIPT_VERIFY_P2SH
from bitcoin.core.script import CScript, SignatureHash, SIGHASH_ALL
from bitcoin.core.script import OP_DUP, OP_HASH160, OP_EQUALVERIFY, OP_CHECKSIG
from bitcoin.core.script import OP_RETURN, OP_CHECKMULTISIGVERIFY
from base64 import b64encode, b64decode

LOCAL_API = JSONRPCAPI()
REMOTE_API = JSONRPCAPI()

LOCAL = LOCAL_API.dispatcher.add_method
REMOTE = REMOTE_API.dispatcher.add_method

def serialize_bytes(bytedata):
    return b64encode(bytedata).decode()

def deserialize_bytes(b64data):
    return b64decode(b64data.encode())

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
    change = CMutableTxOut(-amount, g.bit.getnewaddress().to_scriptPubKey())
    return out, change

def anchor_script(my_pubkey, their_pubkey):
    """Generate the output script for the anchor transaction."""
    script = CScript([2, my_pubkey, their_pubkey, 2, OP_CHECKMULTISIGVERIFY])
    return script.to_p2sh_scriptPubKey()

def get_pubkey():
    """Get a new pubkey."""
    return g.bit.validateaddress(g.bit.getnewaddress())['pubkey']

@LOCAL
def create(url, mymoney, theirmoney, fees):
    """Open a payment channel."""
    bob = jsonrpcproxy.Proxy(url)
    coins, change = select_coins(mymoney + fees)
    serialized_coins = [serialize_bytes(coin.serialize()) for coin in coins]
    serialized_change = serialize_bytes(change.serialize())
    pubkey = get_pubkey()
    serialized_pubkey = serialize_bytes(pubkey)
    transaction = CMutableTransaction.deserialize(deserialize_bytes(
        bob.open_channel(theirmoney, mymoney, fees,
                         serialized_coins, serialized_change,
                         serialized_pubkey)))
    transaction = g.bit.signrawtransaction(transaction)
    assert transaction['complete']
    transaction = transaction['tx']
    g.bit.sendrawtransaction(transaction)
    with g.dat:
        g.dat.execute("INSERT INTO CHANNELS(amount) VALUES (?)", (mymoney,))
    return True

@LOCAL
def getbalance():
    """Get the balance including funds locked in payment channels."""
    lightning_balance = g.dat.execute("SELECT * FROM CHANNELS").fetchone()[0]
    bitcoin_balance = g.bit.getbalance()
    return lightning_balance + bitcoin_balance

@LOCAL
def send(url, amount):
    """Send coin in the channel."""
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
def open_channel(mymoney, theirmoney, fees, their_coins, their_change,
                 their_pubkey):
    """Open a payment channel."""
    their_coins = [CMutableTxIn.deserialize(deserialize_bytes(coin))
                   for coin in their_coins]
    their_change = CMutableTxOut.deserialize(deserialize_bytes(their_change))
    their_pubkey = deserialize_bytes(their_pubkey)
    coins, change = select_coins(mymoney + fees)
    anchor_output_script = anchor_script(get_pubkey(), their_pubkey)
    payment = CMutableTxOut(mymoney + theirmoney, anchor_output_script)
    transaction = CMutableTransaction(
        their_coins + coins,
        [payment, change, their_change])
    transaction = g.bit.signrawtransaction(transaction)
    print(transaction)
    #assert transaction['complete']
    transaction = transaction['tx']
    with g.dat:
        g.dat.execute("INSERT INTO CHANNELS(amount) VALUES (?)", (mymoney,))
    return serialize_bytes(transaction.serialize())
