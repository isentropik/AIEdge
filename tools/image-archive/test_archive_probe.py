"""Failure-path checks for the synthetic receiver probe."""
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from probe_archive_receiver import post, run_probe, ProbeError


class ProbeTests(unittest.TestCase):
    def test_response_limits_and_no_redirect(self):
        for status, body, message in ((302, b'', 'HTTP 302'), (201, b'x'*8193, 'exceeds'),
                                      (201, b'not json', 'Invalid JSON'), (201, b'[]', 'not an object')):
            with self.subTest(status=status, message=message), patch('probe_archive_receiver.http.client.HTTPSConnection') as factory:
                connection=factory.return_value
                response=connection.getresponse.return_value
                response.status=status;response.read.return_value=body
                with self.assertRaisesRegex(ProbeError,message):
                    post('localhost',8766,ssl.create_default_context(),'x'*40,'/v1/settings',b'data',{},1)
                connection.request.assert_called_once()
                connection.close.assert_called_once()
                if status == 201: response.read.assert_called_once_with(8193)

    def test_failure_never_retries_or_echoes_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            token=Path(directory)/'token';token.write_text('secret'*8,encoding='utf-8')
            with patch('probe_archive_receiver.ssl.create_default_context') as trust, patch('probe_archive_receiver.post', side_effect=TimeoutError('secret'*8)) as request:
                with self.assertRaisesRegex(ProbeError,'settings upload: TimeoutError') as caught:
                    run_probe('localhost',8766,'ca.pem',token,1)
                self.assertNotIn('secret',str(caught.exception))
                request.assert_called_once();trust.assert_called_once_with(cafile='ca.pem')

    def test_tampered_receipt_stops_before_image(self):
        with tempfile.TemporaryDirectory() as directory:
            token=Path(directory)/'token';token.write_text('x'*40,encoding='utf-8')
            with patch('probe_archive_receiver.ssl.create_default_context'), patch('probe_archive_receiver.post', return_value=(201,{'verified_readback':True})) as request:
                with self.assertRaisesRegex(ProbeError,'Unexpected settings receipt'):
                    run_probe('localhost',8766,'ca.pem',token,1)
                request.assert_called_once()


if __name__=='__main__': unittest.main()
