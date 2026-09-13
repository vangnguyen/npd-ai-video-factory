"""Exact approval, verify-only and process capture regressions; transport mocked."""
from datetime import datetime
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import claim_only_terminalization as terminal
import claim_terminalization_entry as entry
from test_claim_only_terminalization import NOW, fixture

class FrozenDatetime(datetime):
    @classmethod
    def now(cls,tz=None):return NOW

class EntryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.plan,self.live=fixture(self.root/'fixture')
        self.plan['terminalization_tool_sha256']=terminal.sha(b'synthetic')
        self.authority=self.root/'authority';self.owner=terminal.approval_text(self.plan).encode()
        self.freeze=patch.object(terminal,'datetime',FrozenDatetime);self.freeze.start();self.addCleanup(self.freeze.stop)
    def test_verify_prepared_does_not_load_approval_or_call_transport(self):
        argv=['entry','--verify-prepared','--plan','synthetic','--tool','synthetic','--profile','synthetic']
        stream=io.StringIO()
        with patch('sys.argv',argv),patch.object(entry,'checked_inputs',return_value=(self.plan,b'synthetic',{})),patch.object(entry,'strict_argv',side_effect=AssertionError('SSH reached')),patch.object(entry,'execute',side_effect=AssertionError('execution reached')),patch('sys.stdout',stream):entry.main()
        self.assertEqual(json.loads(stream.getvalue())['owner_terminalization_approval'],'NOT_GRANTED')
        self.assertFalse(self.authority.exists())
    def test_wrong_or_old_owner_message_denied_before_authority_or_ssh(self):
        invoker=Mock(side_effect=AssertionError('remote reached'))
        with patch.object(entry,'strict_argv',side_effect=AssertionError('SSH reached')):
            for raw in (b'old pilot approval',self.owner+b' ',b''):
                with self.subTest(raw_length=len(raw)),self.assertRaisesRegex(terminal.TerminalizationStop,'NOT_VERBATIM'):
                    entry.execute(self.plan,b'synthetic',{},raw,self.authority,invoker=invoker)
        invoker.assert_not_called();self.assertFalse(self.authority.exists())
    def test_expired_owner_message_denied_before_authority_or_ssh(self):
        class Expired(datetime):
            @classmethod
            def now(cls,tz=None):return terminal.utc(self.plan['deadline_utc'])
        with patch.object(terminal,'datetime',Expired),patch.object(entry,'strict_argv',side_effect=AssertionError('SSH reached')):
            with self.assertRaisesRegex(terminal.TerminalizationStop,'OUTSIDE_WINDOW'):entry.execute(self.plan,b'synthetic',{},self.owner,self.authority)
        self.assertFalse(self.authority.exists())
    def test_already_used_authority_cannot_replay(self):
        self.authority.mkdir()
        with patch.object(entry,'strict_argv',side_effect=AssertionError('SSH reached')):
            with self.assertRaisesRegex(terminal.TerminalizationStop,'ALREADY_USED'):entry.execute(self.plan,b'synthetic',{},self.owner,self.authority)
    def test_wrong_tool_denied_before_ssh_or_authority(self):
        with patch.object(entry,'strict_argv',side_effect=AssertionError('SSH reached')):
            with self.assertRaisesRegex(terminal.TerminalizationStop,'TOOL_HASH_MISMATCH'):entry.execute(self.plan,b'modified',{},self.owner,self.authority)
        self.assertFalse(self.authority.exists())
    def test_failed_child_capture_precedes_error_and_retains_stream_hashes(self):
        invoker=Mock(return_value=subprocess.CompletedProcess([],2,b'{"status":"FAIL_CLOSED"}',b'synthetic stderr'))
        with patch.object(entry,'strict_argv',return_value=['synthetic-never-network']):
            with self.assertRaisesRegex(terminal.TerminalizationStop,'CAPTURE_PRESERVED'):entry.execute(self.plan,b'synthetic',{},self.owner,self.authority,invoker=invoker)
        value=terminal.decode((self.authority/'TERMINALIZATION_CAPTURE.json').read_bytes())
        self.assertEqual(value['child_returncode'],2);self.assertEqual(value['stdout_sha256'],terminal.sha(b'{"status":"FAIL_CLOSED"}'))
        self.assertEqual(value['stderr_sha256'],terminal.sha(b'synthetic stderr'));self.assertFalse(value['shell'])
    def test_timeout_partial_output_captured_without_claim_retry(self):
        invoker=Mock(side_effect=subprocess.TimeoutExpired('synthetic',1,output=b'partial',stderr=b''))
        with patch.object(entry,'strict_argv',return_value=['synthetic-never-network']):
            with self.assertRaisesRegex(terminal.TerminalizationStop,'CAPTURE_PRESERVED'):entry.execute(self.plan,b'synthetic',{},self.owner,self.authority,invoker=invoker)
        value=terminal.decode((self.authority/'TERMINALIZATION_CAPTURE.json').read_bytes())
        self.assertEqual(value['transport_error'],'TIMEOUT');self.assertEqual((self.authority/'TERMINALIZATION.stdout.txt').read_bytes(),b'partial')
        self.assertEqual(invoker.call_count,1)

if __name__=='__main__':unittest.main()
