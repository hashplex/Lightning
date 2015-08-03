"""Integration testing."""

import os.path
import unittest
import time
from bitcoin.core import CMutableTransaction
import create_regnet
from destroy_regnet import stop
from serverutil import from_json

class TestChannel(unittest.TestCase):
    """Run basic tests on payment channels."""
    def propagate(self):
        """Ensure all nodes up to date."""
        while len(set(tuple(sorted(node.bit.getrawmempool()))
                      for node in [self.alice, self.bob, self.carol])) > 1:
            time.sleep(0.5)
        self.carol.bit.generate(1)
        while self.alice.bit.getblockcount() != self.carol.bit.getblockcount():
            time.sleep(0.5)

    def setUp(self):
        proxies = create_regnet.main()
        self.alice, self.bob, self.carol = proxies
        self.carol.bit.generate(101)
        self.propagate()
        self.carol.bit.sendmany(
            "",
            {self.alice.bit.getnewaddress(): 100000000,
             self.bob.bit.getnewaddress(): 100000000,
            })
        self.propagate()

    def tearDown(self):
        pass #destroy_regnet.main()

    def test_setup(self):
        """Test that the setup worked."""
        self.assertEqual(self.alice.bit.getbalance(), 100000000)
        self.assertEqual(self.bob.bit.getbalance(), 100000000)

    def test_basic(self):
        """Test basic operation of a payment channel."""
        self.alice.lit.create(self.bob.lurl, 50000000, 25000000)
        self.propagate()
        afee = 50000000 - self.alice.bit.getbalance()
        bfee = 75000000 - self.bob.bit.getbalance()
        self.assertGreaterEqual(afee, 0)
        self.assertGreaterEqual(bfee, 0)
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 50000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 25000000)
        self.bob.lit.send(self.alice.lurl, 5000000)
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 55000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 20000000)
        self.alice.lit.send(self.bob.lurl, 10000000)
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 45000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 30000000)
        self.bob.lit.close(self.alice.lurl)
        self.propagate()
        self.assertGreaterEqual(self.alice.bit.getbalance(), 95000000 - afee)
        self.assertGreaterEqual(self.bob.bit.getbalance(), 105000000 - bfee)

    def test_stress(self):
        """Test edge cases in payment channels."""
        self.alice.lit.create(self.bob.lurl, 25000000, 50000000)
        self.propagate()
        self.carol.lit.create(self.alice.lurl, 50000000, 25000000)
        self.propagate()
        afee = 50000000 - self.alice.bit.getbalance()
        bfee = 50000000 - self.bob.bit.getbalance()
        self.assertGreaterEqual(afee, 0)
        self.assertGreaterEqual(bfee, 0)
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 25000000)
        self.assertEqual(self.alice.lit.getbalance(self.carol.lurl), 25000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 50000000)
        self.assertEqual(self.carol.lit.getbalance(self.alice.lurl), 50000000)
        self.carol.lit.send(self.alice.lurl, 25000000)
        self.assertEqual(self.alice.lit.getbalance(self.carol.lurl), 50000000)
        self.assertEqual(self.carol.lit.getbalance(self.alice.lurl), 25000000)
        self.alice.lit.send(self.carol.lurl, 15000000)
        self.assertEqual(self.alice.lit.getbalance(self.carol.lurl), 35000000)
        self.assertEqual(self.carol.lit.getbalance(self.alice.lurl), 40000000)
        self.bob.lit.send(self.alice.lurl, 50000000)
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 75000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 0)
        self.alice.lit.send(self.bob.lurl, 75000000)
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 0)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 75000000)
        self.alice.lit.close(self.bob.lurl)
        self.propagate()
        self.assertGreaterEqual(self.alice.bit.getbalance(), 50000000 - afee)
        self.assertGreaterEqual(self.bob.bit.getbalance(), 125000000 - bfee)
        self.alice.lit.close(self.carol.lurl)
        self.propagate()
        self.assertGreaterEqual(self.alice.bit.getbalance(), 85000000 - afee)

    def test_malicious(self):
        """Test recovery from a malicious counterparty."""
        self.alice.lit.create(self.bob.lurl, 50000000, 25000000)
        self.propagate()
        afee = 50000000 - self.alice.bit.getbalance()
        bfee = 75000000 - self.bob.bit.getbalance()
        self.assertGreaterEqual(afee, 0)
        self.assertGreaterEqual(bfee, 0)
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 50000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 25000000)
        self.bob.lit.send(self.alice.lurl, 5000000)
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 55000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 20000000)
        commitment = self.alice.lit.getcommitmenttransactions(self.bob.lurl)
        commitment = [from_json(transaction, CMutableTransaction)
                      for transaction in commitment]
        self.alice.lit.send(self.bob.lurl, 10000000)
        self.assertEqual(self.alice.lit.getbalance(self.bob.lurl), 45000000)
        self.assertEqual(self.bob.lit.getbalance(self.alice.lurl), 30000000)
        stop(self.alice.lpid)
        for transaction in commitment:
            self.alice.bit.sendrawtransaction(transaction)
            self.propagate()
        time.sleep(1)
        self.propagate()
        self.assertGreaterEqual(self.bob.bit.getbalance(), 150000000 - bfee)

class TestLightning(unittest.TestCase):
    """Run basic tests on payment channels."""
    def propagate(self):
        """Ensure all nodes up to date."""
        while len(set(tuple(sorted(node.bit.getrawmempool()))
                      for node in [self.alice, self.bob, self.carol])) > 1:
            time.sleep(0.5)
        self.carol.bit.generate(1)
        while self.alice.bit.getblockcount() != self.carol.bit.getblockcount():
            time.sleep(0.5)

    def setUp(self):
        proxies = create_regnet.main()
        self.alice, self.bob, self.carol = proxies
        self.carol.bit.generate(101)
        self.propagate()
        self.carol.bit.sendmany(
            "",
            {self.alice.bit.getnewaddress(): 100000000,
             self.bob.bit.getnewaddress(): 100000000,
            })
        self.propagate()
        self.alice.lit.create(self.carol.lurl, 50000000, 50000000)
        self.propagate()
        self.bob.lit.create(self.carol.lurl, 50000000, 50000000)
        self.propagate()

    def tearDown(self):
        pass #destroy_regnet.main()

    def test_setup(self):
        """Test that the setup worked."""
        self.assertEqual(self.alice.lit.getbalance(self.carol.lurl), 50000000)
        self.assertEqual(self.bob.lit.getbalance(self.carol.lurl), 50000000)
        self.assertEqual(self.carol.lit.getbalance(self.alice.lurl), 50000000)
        self.assertEqual(self.carol.lit.getbalance(self.bob.lurl), 50000000)

    def test_payment(self):
        """Test multi-hop payment."""
        self.alice.lit.send(self.bob.lurl, 5000000)
        fee = 45000000 - self.alice.lit.getbalance(self.carol.lurl)
        self.assertGreaterEqual(fee, 0)
        self.assertEqual(self.carol.lit.getbalance(self.alice.lurl), 55000000 + fee)
        self.assertEqual(self.bob.lit.getbalance(self.carol.lurl), 55000000)
        self.assertEqual(self.carol.lit.getbalance(self.bob.lurl), 45000000)

if __name__ == '__main__':
    unittest.main()
