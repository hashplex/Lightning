"""Private (local) API for a lightning node."""

import jsonrpcproxy
from jsonrpc.backend.flask import JSONRPCAPI
from flask import g
from bitcoin.core import COutPoint, CMutableTxOut, CMutableTxIn
from bitcoin.core import CMutableTransaction
from bitcoin.core.scripteval import VerifyScript, SCRIPT_VERIFY_P2SH
from bitcoin.core.script import CScript, SignatureHash, SIGHASH_ALL
from bitcoin.core.script import OP_CHECKMULTISIG
from base64 import b64encode, b64decode

LOCAL_API = JSONRPCAPI()
REMOTE_API = JSONRPCAPI()

LOCAL = LOCAL_API.dispatcher.add_method
REMOTE = REMOTE_API.dispatcher.add_method

def serialize_bytes(bytedata):
    """Convert bytes to str."""
    return b64encode(bytedata).decode()

def deserialize_bytes(b64data):
    """Convert str to bytes."""
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

@LOCAL
def create(url, mymoney, theirmoney, fees):
    """Open a payment channel."""
    bob = jsonrpcproxy.Proxy(url)
    coins, change = select_coins(mymoney + fees)
    serialized_coins = [serialize_bytes(coin.serialize()) for coin in coins]
    serialized_change = serialize_bytes(change.serialize())
    pubkey = get_pubkey()
    serialized_pubkey = serialize_bytes(pubkey)
    transaction, redeem = bob.open_channel(
        theirmoney, mymoney, fees,
        serialized_coins, serialized_change,
        serialized_pubkey)
    transaction = CMutableTransaction.deserialize(deserialize_bytes(
        transaction))
    anchor_output_script = CScript(deserialize_bytes(redeem))
    transaction = g.bit.signrawtransaction(transaction)
    assert transaction['complete']
    transaction = transaction['tx']
    g.bit.sendrawtransaction(transaction)
    with g.dat:
        g.dat.execute(
            "INSERT INTO CHANNELS(amount, anchor, fees, redeem) VALUES (?, ?, ?, ?)",
            (mymoney, transaction.GetHash(), fees, anchor_output_script))
    return True

def lightning_balance():
    """Get the balance in lightning channels exclusively."""
    return sum(
        row[0]
        for row in g.dat.execute("SELECT amount FROM CHANNELS")
        )

@LOCAL
def getbalance():
    """Get the balance including funds locked in payment channels."""
    return lightning_balance() + g.bit.getbalance()

@LOCAL
def send(url, amount):
    """Send coin in the channel."""
    with g.dat:
        g.dat.execute(
            "UPDATE CHANNELS SET amount = ?", (lightning_balance() - amount,))
    bob = jsonrpcproxy.Proxy(url)
    bob.recieve(amount)
    return True

@LOCAL
def close(url):
    """Close a channel."""
    bob = jsonrpcproxy.Proxy(url)
    amount, anchor, fees, redeem = g.dat.execute("SELECT * from CHANNELS").fetchone()
    redeem = CScript(redeem)
    output = CMutableTxOut(
        amount - fees, g.bit.getnewaddress().to_scriptPubKey())
    serialized_output = serialize_bytes(output.serialize())
    transaction, bob_sig = bob.close_channel(serialized_output)
    transaction = CMutableTransaction.deserialize(deserialize_bytes(
        transaction))
    transaction = CMutableTransaction.from_tx(transaction)
    anchor = transaction.vin[0]
    bob_sig = deserialize_bytes(bob_sig)
    sighash = SignatureHash(redeem, transaction, 0, SIGHASH_ALL)
    sig = g.seckey.sign(sighash) + bytes([SIGHASH_ALL])
    anchor.scriptSig = CScript([0, sig, bob_sig, redeem])
    VerifyScript(anchor.scriptSig, redeem.to_p2sh_scriptPubKey(),
                 transaction, 0, (SCRIPT_VERIFY_P2SH,))
    g.bit.sendrawtransaction(transaction)
    with g.dat:
        g.dat.execute("DELETE FROM CHANNELS")
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
    anchor_output_address = anchor_output_script.to_p2sh_scriptPubKey()
    payment = CMutableTxOut(mymoney + theirmoney, anchor_output_address)
    transaction = CMutableTransaction(
        their_coins + coins,
        [payment, change, their_change])
    transaction = g.bit.signrawtransaction(transaction)
    print(transaction)
    #assert transaction['complete']
    transaction = transaction['tx']
    with g.dat:
        g.dat.execute(
            "INSERT INTO CHANNELS(amount, anchor, fees, redeem) VALUES (?, ?, ?, ?)",
            (mymoney, transaction.GetHash(), fees, anchor_output_script))
    return (serialize_bytes(transaction.serialize()),
            serialize_bytes(anchor_output_script))

@REMOTE
def recieve(amount):
    """Recieve money."""
    with g.dat:
        g.dat.execute(
            "UPDATE CHANNELS SET amount = ?", (lightning_balance() + amount,))
    return True

@REMOTE
def close_channel(their_output):
    """Close a channel."""
    their_output = CMutableTxOut.deserialize(deserialize_bytes(their_output))
    amount, anchor, fees, redeem = g.dat.execute("SELECT * from CHANNELS").fetchone()
    redeem = CScript(redeem)
    output = CMutableTxOut(
        amount - fees, g.bit.getnewaddress().to_scriptPubKey())
    anchor = CMutableTxIn(COutPoint(anchor, 0))
    transaction = CMutableTransaction([anchor,], [output, their_output])
    sighash = SignatureHash(redeem, transaction, 0, SIGHASH_ALL)
    sig = g.seckey.sign(sighash) + bytes([SIGHASH_ALL])
    with g.dat:
        g.dat.execute("DELETE FROM CHANNELS")
    return (serialize_bytes(transaction.serialize()),
            serialize_bytes(sig))
