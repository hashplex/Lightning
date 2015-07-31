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
from serverutil import to_json, from_json

API, REMOTE = api_factory('channel')

SIGNALS = Namespace()
CHANNEL_OPENED = SIGNALS.signal('CHANNEL_OPENED')

def init(conf):
    """Set up the database."""
    conf['database_path'] = os.path.join(conf['datadir'], 'channel.dat')
    if not os.path.isfile(conf['database_path']):
        dat = sqlite3.connect(conf['database_path'])
        with dat:
            dat.execute("CREATE TABLE CHANNELS(address, amount, anchor, fees, redeem)")

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
    row = g.dat.execute(
        "SELECT address, amount from CHANNELS WHERE address = ?", (address,)
    ).fetchone()
    if row is None:
        raise Exception("Unknown address", address)
    address, current_amount = row
    with g.dat:
        g.dat.execute(
            "UPDATE CHANNELS SET amount = ? WHERE address = ?", (current_amount + amount, address))

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
        to_json(coins), to_json(change),
        to_json(pubkey))
    transaction = from_json(transaction, CMutableTransaction)
    anchor_output_script = from_json(redeem, CScript)
    transaction = g.bit.signrawtransaction(transaction)
    assert transaction['complete']
    transaction = transaction['tx']
    g.bit.sendrawtransaction(transaction)
    with g.dat:
        g.dat.execute(
            "INSERT INTO CHANNELS(address, amount, anchor, fees, redeem) VALUES (?, ?, ?, ?, ?)",
            (url, mymoney, transaction.GetHash(), fees, anchor_output_script))
    bob.update_anchor(g.addr, to_json(transaction.GetHash()))
    CHANNEL_OPENED.send('channel', address=url)
    return True

def send(url, amount):
    """Send coin in the channel.

    Negotiate the update of the channel opened with node url paying that node
    amount more satoshis than before. No fees should be collected by this
    method.
    """
    update_db(url, -amount)
    bob = jsonrpcproxy.Proxy(url+'channel/')
    bob.recieve(g.addr, amount)
    return True

def getbalance(url):
    """Get the balance of funds in a payment channel.

    This returns the number of satoshis you can spend in the channel
    with the node at url. This should have no side effects.
    """
    return g.dat.execute("SELECT amount FROM CHANNELS WHERE address = ?", (url,)).fetchone()[0]

def close(url):
    """Close a channel.

    Close the currently open channel with node url. Any funds in the channel
    are paid to the wallet, along with any fees collected by create which
    were unnecessary."""
    bob = jsonrpcproxy.Proxy(url+'channel/')
    row = g.dat.execute("SELECT * from CHANNELS WHERE address = ?", (url,)).fetchone()
    if row is None:
        raise Exception("Unknown address", url)
    address, current_amount, anchor, fees, redeem = row
    redeem = CScript(redeem)
    output = CMutableTxOut(
        current_amount, g.bit.getnewaddress().to_scriptPubKey())
    transaction, bob_sig = bob.close_channel(g.addr, to_json(output))
    transaction = from_json(transaction, CMutableTransaction)
    anchor = transaction.vin[0]
    bob_sig = from_json(bob_sig, bytes)
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
    CHANNEL_OPENED.send('channel', address=address)
    return (to_json(transaction), to_json(anchor_output_script))

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
    their_output = from_json(their_output, CMutableTxOut)
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
    return (to_json(transaction), to_json(sig))
