import unittest

from app.cli import NOME, saudacao


class TestCli(unittest.TestCase):
    def test_saudacao(self):
        self.assertEqual(saudacao("ana"), f"{NOME}: olá, ana")
