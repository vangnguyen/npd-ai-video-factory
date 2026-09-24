"""Regression coverage for Windows OpenSSH paths containing whitespace."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_transport as transport


class WindowsOpenSshPathContractTests(unittest.TestCase):
    def test_file_option_quotes_and_normalizes_whitespace_path(self):
        source = r"C:\Users\VANG NGUYEN\.ssh\pinned known_hosts"
        self.assertEqual(
            transport.openssh_file_option('UserKnownHostsFile', source),
            'UserKnownHostsFile="C:/Users/VANG NGUYEN/.ssh/pinned known_hosts"',
        )

    def test_file_option_rejects_injection_and_unknown_names(self):
        for value in ('', 'a\nb', 'a\rb', 'a\x00b', 'a"b'):
            with self.subTest(value=value), self.assertRaises(Exception):
                transport.openssh_file_option('UserKnownHostsFile', value)
        with self.assertRaises(Exception):
            transport.openssh_file_option('IdentityFile', r'C:\safe')

    def test_ssh_and_scp_argv_share_exact_quoted_option(self):
        expected = 'UserKnownHostsFile="C:/Users/VANG NGUYEN/.ssh/pinned known_hosts"'
        profile = {
            'operation_id': 'PHASE9-LIMITED-PILOT-RCA06-11111111-1111-4111-8111-111111111111',
            'transport': {
                'host': '157.10.201.169', 'port': 22, 'user': 'root',
                'known_hosts_client_path': r'C:\Users\VANG NGUYEN\.ssh\pinned known_hosts',
                'ssh_executable': 'ssh.exe', 'scp_executable': 'scp.exe',
                'keygen_executable': 'ssh-keygen.exe', 'known_hosts': 'known_hosts',
                'identity_file': 'identity', 'host_fingerprint': 'SHA256:fixture',
            },
        }
        for key in ('ssh_executable', 'scp_executable', 'keygen_executable', 'known_hosts'):
            profile['transport'][key + '_sha256'] = 'fixture-sha'
        with mock.patch.object(transport, 'verify_operation_identity'):
            with mock.patch.object(transport.Path, 'is_file', return_value=True), \
                    mock.patch.object(transport.Path, 'is_symlink', return_value=False), \
                    mock.patch.object(transport, 'sha', return_value='fixture-sha'), \
                    mock.patch.object(
                        transport.subprocess,
                        'run',
                        return_value=subprocess.CompletedProcess([], 0, b'256 SHA256:fixture fixture (ED25519)\n', b''),
                    ):
                ssh = transport.strict_argv(profile, ['true'])
                scp = transport.stage_argv(profile, Path('candidate.oci.tar'), profile['operation_id'])
        self.assertEqual(ssh.count(expected), 1)
        self.assertEqual(scp.count(expected), 1)
        self.assertIn(expected, scp)

    @unittest.skipUnless(os.name == 'nt', 'Windows OpenSSH parser contract')
    def test_real_windows_openssh_parser_preserves_whole_space_path(self):
        ssh = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32' / 'OpenSSH' / 'ssh.exe'
        if not ssh.is_file():
            self.skipTest('Windows OpenSSH is unavailable')
        with tempfile.TemporaryDirectory(prefix='npd openssh parser ') as temporary:
            known_hosts = Path(temporary) / 'pinned known_hosts'
            known_hosts.write_text('fixture-only\n', encoding='utf-8')
            option = transport.openssh_file_option('UserKnownHostsFile', str(known_hosts))
            result = subprocess.run(
                [str(ssh), '-G', '-F', 'NUL', '-o', 'StrictHostKeyChecking=yes',
                 '-o', option, 'root@127.0.0.1'],
                capture_output=True, text=True, shell=False, timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = [line for line in result.stdout.splitlines() if line.startswith('userknownhostsfile ')]
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].split(' ', 1)[1], str(known_hosts).replace('\\', '/'))


if __name__ == '__main__':
    unittest.main()
