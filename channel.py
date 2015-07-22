"""Private (local) API for a lightning node."""

import jsonrpcproxy
from jsonrpc.backend.flask import JSONRPCAPI
from flask import g
import bitcoin
import bitcoin.wallet
from bitcoin.core import b2x, lx, COIN
from bitcoin.core import COutPoint, CMutableTxOut, CMutableTxIn
from bitcoin.core import CMutableTransaction, Hash160
from bitcoin.core.scripteval import VerifyScript, SCRIPT_VERIFY_P2SH
from bitcoin.core.script import CScript, SignatureHash, SIGHASH_ALL
from bitcoin.core.script import OP_DUP, OP_HASH160, OP_EQUALVERIFY, OP_CHECKSIG
from bitcoin.core.script import OP_RETURN

LOCAL_API = JSONRPCAPI()
REMOTE_API = JSONRPCAPI()

LOCAL = LOCAL_API.dispatcher.add_method
REMOTE = REMOTE_API.dispatcher.add_method

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

def anchor_script():
    """Generate the output script for the anchor transaction."""
    return CScript([OP_RETURN]).to_p2sh_scriptPubKey()

@LOCAL
def create(url, mymoney, theirmoney, fees):
    """Open a payment channel."""
    bob = jsonrpcproxy.Proxy(url)
    bob.open_channel(theirmoney, mymoney, fees)
    payment = CMutableTxOut(mymoney, anchor_script())
    coins, change = select_coins(mymoney + fees)
    transaction = CMutableTransaction(coins, [payment, change])
    transaction = g.bit.signrawtransaction(transaction)
    assert transaction['complete']
    transaction = transaction['tx']
    g.bit.sendrawtransaction(transaction)
    return True

@LOCAL
def getbalance():
    """Get the balance including funds locked in payment channels."""
    return 0

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
def open_channel(mymoney, theirmoney, fees):
    """Open a payment channel."""
    payment = CMutableTxOut(mymoney, anchor_script())
    coins, change = select_coins(mymoney + fees)
    transaction = CMutableTransaction(coins, [payment, change])
    transaction = g.bit.signrawtransaction(transaction)
    print(transaction)
    assert transaction['complete']
    transaction = transaction['tx']
    g.bit.sendrawtransaction(transaction)
    return True
