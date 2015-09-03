"""Integration testing."""

import unittest
import time
from test import regnet

class TestChannel(unittest.TestCase):
    """Run basic tests on payment channels."""

    @classmethod
    def setUpClass(cls):
        cls.cache = regnet.make_cache()

    @classmethod
    def tearDownClass(cls):
        cls.cache.cleanup()

    def propagate(self):
        """Ensure all nodes up to date."""
        self.net.generate()

    def setUp(self):
        # Set up 3 nodes: Alice, Bob, and Carol
        self.net = regnet.create(datadir=None, cache=self.cache)
        self.alice, self.bob, self.carol = self.net[0], self.net[1], self.net[2]
        # self.alice.bit is an interface to bitcoind,
        # self.alice.lit talks to the lightning node
        # self.alice.lurl is Alice's identifier

    def tearDown(self):
        self.net.stop(hard=True, cleanup=True)

    def test_setup(self):
        """Test that the setup worked."""
        # Alice and Bob each start with 1.00 BTC
        self.assertEqual(self.alice.bit.getbalance(), 100000000)
        self.assertEqual(self.bob.bit.getbalance(), 100000000)

    def test_basic(self):
        """Test basic operation of a payment channel."""
        # Open a channel between Alice and Bob
        try: 
            self.alice.lit.create(self.bob.lurl, 50000000, 25000000)    
        finally: 
            self.alice.lightning.print_log()
            self.bob.lightning.print_log()            

        self.propagate()
        # There are some fees associated with opening a channel
        afee = 50000000 - self.alice.bit.getbalance()
        bfee = 75000000 - self.bob.bit.getbalance()
        self.assertGreaterEqual(afee, 0)
        self.assertGreaterEqual(bfee, 0)
        # (Balance) Alice: 0.50 BTC, Bob: 0.25 BTC
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 50000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 25000000)
        # Bob sends Alice 0.05 BTC
        self.bob.lit.send(self.alice.lurl, 5000000)
        # (Balance) Alice: 0.55 BTC, Bob: 0.20 BTC
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 55000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 20000000)
        # Now Alice sends Bob 0.10 BTC
        self.alice.lit.send(self.bob.lurl, 10000000)
        # (Balance) Alice: 0.45 BTC, Bob: 0.30 BTC
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 45000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 30000000)
        # Bob closes the channel
        self.bob.lit.close(self.alice.lurl)
        self.propagate()
        # The Lightning balance is returned to the bitcoin wallet
        # If any coin was held for fees which were never paid,
        # they are refunded, so the balance may be more than expected.
        self.assertGreaterEqual(self.alice.bit.getbalance(), 95000000 - afee)
        self.assertGreaterEqual(self.bob.bit.getbalance(), 105000000 - bfee)

    def test_stress(self):
        """Test edge cases in payment channels."""
        # Open *two* payment channels Bob - Alice - Carol
        self.alice.lit.create(self.bob.lurl, 25000000, 50000000)
        self.propagate()
        self.carol.lit.create(self.alice.lurl, 50000000, 25000000)
        self.propagate()
        # Account for fees
        afee = 50000000 - self.alice.bit.getbalance()
        bfee = 50000000 - self.bob.bit.getbalance()
        self.assertGreaterEqual(afee, 0)
        self.assertGreaterEqual(bfee, 0)
        # Balance (A-C) Alice: 0.25 BTC, Carol: 0.50 BTC
        # Balance (B-A) Bob:   0.50 BTC, Alice: 0.25 BTC
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 25000000)
        self.assertEqual(self.alice.lit.getbalance(self.carol.lurl), 25000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 50000000)
        self.assertEqual(self.carol.lit.getbalance(self.alice.lurl), 50000000)
        # Carol sends 0.25 BTC to Alice
        self.carol.lit.send(self.alice.lurl, 25000000)
        # Balance (A-C) Alice: 0.50 BTC, Carol: 0.25 BTC
        self.assertEqual(self.alice.lit.getbalance(self.carol.lurl), 50000000)
        self.assertEqual(self.carol.lit.getbalance(self.alice.lurl), 25000000)
        # Alice sends 0.15 BTC to Carol
        self.alice.lit.send(self.carol.lurl, 15000000)
        # Balance (A-C) Alice: 0.35 BTC, Carol: 0.40 BTC
        self.assertEqual(self.alice.lit.getbalance(self.carol.lurl), 35000000)
        self.assertEqual(self.carol.lit.getbalance(self.alice.lurl), 40000000)
        # Bob sends Alice 0.50 BTC (his whole balance)
        self.bob.lit.send(self.alice.lurl, 50000000)
        # Balance (B-A) Bob:   0.00 BTC, Alice: 0.75 BTC
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 75000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 0)
        # Alice sends Bob 0.75 BTC (her whole balance)
        self.alice.lit.send(self.bob.lurl, 75000000)
        # Balance (B-A) Bob:   0.75 BTC, Alice: 0.00 BTC
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 0)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 75000000)
        # Alice closes the channel with Bob, on an empty account (Alice opened)
        self.alice.lit.close(self.bob.lurl)
        self.propagate()
        self.assertGreaterEqual(self.alice.bit.getbalance(), 50000000 - afee)
        self.assertGreaterEqual(self.bob.bit.getbalance(), 125000000 - bfee)
        # Alice closes the channel with Carol (Carol opened)
        self.alice.lit.close(self.carol.lurl)
        self.propagate()
        self.assertGreaterEqual(self.alice.bit.getbalance(), 85000000 - afee)

    def test_unilateral_close(self):
        """Test unilateral close."""
        # Set up channel between Alice and Bob
        self.alice.lit.create(self.bob.lurl, 50000000, 25000000)
        self.propagate()
        afee = 50000000 - self.alice.bit.getbalance()
        bfee = 75000000 - self.bob.bit.getbalance()
        self.assertGreaterEqual(afee, 0)
        self.assertGreaterEqual(bfee, 0)
        # Do some transactions
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 50000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 25000000)
        self.bob.lit.send(self.alice.lurl, 5000000)
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 55000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 20000000)
        # Pause Bob
        with self.bob.paused():
            # Publish Alice's commitment transactions
            commitment = self.alice.lit.getcommitmenttransactions(self.bob.lurl)
            for transaction in commitment:
                self.alice.bit.sendrawtransaction(transaction)
                self.propagate()
            time.sleep(1)
            self.propagate()
        self.propagate()
        # Alice and Bob get their money out
        self.assertGreaterEqual(self.bob.bit.getbalance(), 95000000 - bfee)
        self.assertGreaterEqual(self.alice.bit.getbalance(), 105000000 - afee)

    @unittest.expectedFailure
    def test_revoked(self):
        """Test a revoked commitment transaction being published."""
        # Set up channel between Alice and Bob
        self.alice.lit.create(self.bob.lurl, 50000000, 25000000)
        self.propagate()
        afee = 50000000 - self.alice.bit.getbalance()
        bfee = 75000000 - self.bob.bit.getbalance()
        self.assertGreaterEqual(afee, 0)
        self.assertGreaterEqual(bfee, 0)
        # Make a transaction
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 50000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 25000000)
        self.bob.lit.send(self.alice.lurl, 5000000)
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 55000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 20000000)
        # Save Alice's old commitment transactions
        commitment = self.alice.lit.getcommitmenttransactions(self.bob.lurl)
        # Do annother transaction, Alice sends Bob money
        self.alice.lit.send(self.bob.lurl, 10000000)
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 45000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 30000000)
        # Alice publishes her old, revoked commitment transactions
        for transaction in commitment:
            self.alice.bit.sendrawtransaction(transaction)
            self.propagate()
        time.sleep(1)
        self.propagate()
        # Bob ends up with all the money
        self.assertGreaterEqual(self.bob.bit.getbalance(), 150000000 - bfee)

class TestLightning(unittest.TestCase):
    """Run basic tests on payment channels."""

    @classmethod
    def setUpClass(cls):
        cls.cache = regnet.make_cache()

    @classmethod
    def tearDownClass(cls):
        cls.cache.cleanup()

    def propagate(self):
        """Ensure all nodes up to date."""
        self.net.generate()

    def setUp(self):
        # As in TestChannel, set up 3 nodes
        self.net = regnet.create(datadir=None, cache=self.cache)
        self.alice, self.bob, self.carol = self.net[0], self.net[1], self.net[2]
        # Set up channels between so the network is Alice - Carol - Bob
        self.alice.lit.create(self.carol.lurl, 50000000, 50000000)
        self.propagate()
        self.bob.lit.create(self.carol.lurl, 50000000, 50000000)
        self.propagate()

    def tearDown(self):
        self.net.stop(hard=True, cleanup=True)

    def test_setup(self):
        """Test that the setup worked."""
        # (Balance) Alice-Carol: Alice: 0.50 BTC, Carol 0.50 BTC
        #           Carol-Bob  : Carol: 0.50 BTC, Bob   0.50 BTC
        # (Total) Alice: 0.50 BTC, Carol: 1.00 BTC, Bob: 0.50 BTC
        self.assertEqual(self.alice.lit.getbalance(self.carol.lurl), 50000000)
        self.assertEqual(self.bob.lit.getbalance(self.carol.lurl), 50000000)
        self.assertEqual(self.carol.lit.getbalance(self.alice.lurl), 50000000)
        self.assertEqual(self.carol.lit.getbalance(self.bob.lurl), 50000000)

    def test_payment(self):
        """Test multi-hop payment."""
        # Note Alice and Bob do not have a payment channel open directly.
        # They are connected through Carol
        self.alice.lit.send(self.bob.lurl, 5000000)
        # There is a fee associated with multi-hop payments
        fee = 45000000 - self.alice.lit.getbalance(self.carol.lurl)
        self.assertGreaterEqual(fee, 0)
        # (Balance) Alice-Carol: Alice: 0.45 - fee BTC, Carol 0.55 + fee BTC
        #           Carol-Bob  : Carol: 0.45       BTC, Bob   0.55       BTC
        # (Total) Alice: 0.45 - fee BTC, Carol: 1.00 + fee BTC, Bob: 0.55 BTC
        self.assertEqual(self.carol.lit.getbalance(self.alice.lurl), 55000000 + fee)
        self.assertEqual(self.bob.lit.getbalance(self.carol.lurl), 55000000)
        self.assertEqual(self.carol.lit.getbalance(self.bob.lurl), 45000000)
        # Send money the other direction
        self.bob.lit.send(self.alice.lurl, 10000000)
        # Annother fee will be deducted
        fee2 = 45000000 - self.bob.lit.getbalance(self.carol.lurl)
        self.assertGreaterEqual(fee2, 0)
        # (Balance) Alice-Carol: Alice: 0.55 - fee  BTC, Carol 0.45 + fee  BTC
        #           Carol-Bob  : Carol: 0.55 + fee2 BTC, Bob   0.45 - fee2  BTC
        # (Total) Alice: 0.55 - fee BTC, Carol: 1.00 + fee + fee2 BTC, Bob: 0.45 - fee2 BTC
        self.assertEqual(self.carol.lit.getbalance(self.alice.lurl), 45000000 + fee)
        self.assertEqual(self.alice.lit.getbalance(self.carol.lurl), 55000000 - fee)
        self.assertEqual(self.carol.lit.getbalance(self.bob.lurl), 55000000 + fee2)

    @unittest.expectedFailure
    def test_route_close(self):
        """Test routing around closed channels."""
        # Create a new channel between Alice and Bob
        # so all 3 are connected to each other.
        self.alice.lit.create(self.bob.lurl, 25000000, 25000000)
        # Close the connection between Alice and Carol
        self.alice.lit.close(self.carol.lurl)
        self.propagate()
        # Alice sends 0.10 BTC to Carol
        self.alice.lit.send(self.carol.lurl, 10000000)
        # Carol should have recieved money from Bob
        self.assertEqual(self.carol.lit.getbalance(self.bob.lurl), 60000000)

if __name__ == '__main__':
    unittest.main()
