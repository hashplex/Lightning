"""Tests for jsonrpcproxy.py."""

import unittest
import bitcoin
from bitcoin.core.script import CScript
from bitcoin.base58 import CBase58Data
from bitcoin.wallet import P2SHBitcoinAddress, P2PKHBitcoinAddress
from bitcoin.core import CMutableTransaction, CMutableTxIn, CMutableTxOut
from bitcoin.core import COutPoint
from jsonrpcproxy import to_json, from_json, SmartDispatcher, Proxy
bitcoin.SelectParams('regtest')

class TestTranslation(unittest.TestCase):
    def test_json_roundtrip(self):
        VALUES = [
            42, 0, -42, 2100000000000000, -2100000000000000,
            "basic string", "\u1111Unicode", "\U00010000Wide Unicode",
            "\x00\n\t\r\nEscape codes", "\"'\"Quotes", "",
            None,
            b"\x00\x01\xFFBinary data", b"",
            CBase58Data.from_bytes(b'\x00\x01\xFF', 42),
            P2SHBitcoinAddress.from_bytes(b'\x00\x01\xFF'),
            P2PKHBitcoinAddress.from_bytes(b'\x00\x01\xFF'),
            CMutableTxIn(COutPoint(b'\x00'*16+b'\xFF'*16, 42),
                         CScript(b'\x00\x01\xFF'),
                         42),
            CMutableTxOut(42, CScript(b'\x00\x01\xFF')),
            CMutableTransaction([CMutableTxIn(COutPoint(b'\x00'*32, 42),
                                              CScript(b'\x00\x01\xFF'),
                                              42),
                                 CMutableTxIn(COutPoint(b'\xFF'*32, 42),
                                              CScript(b'\xFF\x01\x00'),
                                              43)],
                                [CMutableTxOut(42, CScript(b'\x00\x01\xFF')),
                                 CMutableTxOut(43, CScript(b'\xFF\x01\x00'))],
                                42, 3),
            [1, b'\x00\x01\xFF', "List Test",],
            {'a':1, 'key':b'\xFF\x01\x00', 1:'Dictionary Test'},
            [{3: [0, 1, 2,],}, [[b'\xFFRecursion Test',],],],
        ]
        for value in VALUES:
            with self.subTest(value=value):
                self.assertEqual(from_json(to_json(value)), value)

    def test_None_hiding(self):
        # Our jsonrpc server library gets confused when functions return None
        self.assertNotEqual(to_json(None), None)
        self.assertEqual(from_json(to_json(None)), None)

    def test_CBase58Data_version(self):
        self.assertEqual(from_json(to_json(
            CBase58Data.from_bytes(b'\x00\x01\xFF', 42))).nVersion,
            42)

    def test_tuple(self):
        value = (1, 'a', b'b',)
        self.assertEqual(from_json(to_json(value)), list(value))

class TestDispatcher(unittest.TestCase):
    def setUp(self):
        self.dispatcher = SmartDispatcher()
        self.add = self.dispatcher.add_method

    def test_echo(self):
        self.add(lambda x:x, 'echo')
        echo = self.dispatcher['echo']
        VALUES = [
            42, "str", b"\x00\x01\xFFbytes",
            {1: b"dict",}, [1, "list", b"bytes",],
        ]
        for value in VALUES:
            with self.subTest(value=value):
                self.assertEqual(from_json(echo(to_json(value))), value)

    def test_type(self):
        self.add(lambda x:str(type(x)), 'type')
        typeof = self.dispatcher['type']
        VALUES = [
            42, "str", b"\x00\x01\xFFbytes",
            {1: b"dict",}, [1, "list", b"bytes",],
        ]
        for value in VALUES:
            with self.subTest(value=value):
                self.assertEqual(from_json(typeof(to_json(value))),
                                 str(type(value)))

    def test_error(self):
        class TestException(Exception):
            pass
        @self.add
        def error(args):
            raise TestException(*args)
        error = self.dispatcher['error']
        VALUES = [
            ('ordinary', 1, 2, 'foo',),
            ('bytes', b'\x00\x01\xFF',),
            ('list', [1, 'a', b'b',],),
        ]
        for value in VALUES:
            with self.subTest(value=value):
                self.assertRaises(TestException, error, to_json(value))

        @self.add
        def nested_error():
            raise TestException('nested', TestException('2nd layer'))
        self.assertRaises(TestException, self.dispatcher['nested_error'])
