import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch
from studio.runtime import Connection
from studio.store import Store


@unittest.skipUnless(os.name=='nt','Windows vault')
class ConnectionTests(unittest.TestCase):
    def test_old_auth_failure_cannot_discard_new_session(self):
        with tempfile.TemporaryDirectory() as folder:
            connection=Connection(Store(folder))
            old='simulated-old-session-credential-with-enough-length'
            fresh='simulated-new-session-credential-with-enough-length'
            with patch('studio.runtime.Discord.get',return_value={'id':'123','username':'Synthetic'}):
                connection.accept(old,'test')
                connection.accept(fresh,'test')
            self.assertFalse(connection.expired(hashlib.sha256(old.encode()).hexdigest()))
            self.assertEqual(connection.token,fresh)
            self.assertNotIn(fresh,connection.vault.path.read_bytes().decode('latin1'))

    def test_other_account_cannot_silently_replace_pinned_account(self):
        with tempfile.TemporaryDirectory() as folder:
            connection=Connection(Store(folder))
            with patch('studio.runtime.Discord.get',return_value={'id':'123','username':'Synthetic'}):connection.accept('simulated-current-session-credential-with-enough-length','test')
            with patch('studio.runtime.Discord.get',return_value={'id':'456','username':'Other'}):
                with self.assertRaises(ValueError):connection.accept('simulated-different-session-credential-with-enough-length','test')
            self.assertEqual(connection.account['id'],'123')
