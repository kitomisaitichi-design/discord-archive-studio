import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from studio.discord import Discord, PermissionError


class Response(io.BytesIO):
    headers={'X-RateLimit-Remaining':'5'}
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class NetworkTests(unittest.TestCase):
    def test_403_and_404_stop_after_one_request(self):
        for code in (403,404):
            client=Discord('simulated-no-real-token')
            with patch('studio.discord.build_opener') as opener:
                opener.return_value.open.side_effect=HTTPError('https://discord.com/api/v10/',code,'Denied',{},io.BytesIO(b'{}'))
                with self.assertRaises(PermissionError):client.get('channels/123/messages')
                self.assertEqual(opener.return_value.open.call_count,1)

    def test_429_obeys_retry_after_and_then_succeeds(self):
        client=Discord('simulated-no-real-token');waits=[];client.wait=lambda n:waits.append(n)
        error=HTTPError('https://discord.com/api/v10/',429,'Rate limit',{},io.BytesIO(b'{"retry_after":2}'))
        with patch('studio.discord.build_opener') as opener:
            opener.return_value.open.side_effect=[error,Response(json.dumps({'ok':True}).encode())]
            self.assertTrue(client.get('users/@me')['ok'])
            self.assertIn(3,waits)
            self.assertEqual(opener.return_value.open.call_count,2)


if __name__=='__main__':unittest.main()
