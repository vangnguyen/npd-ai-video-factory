"""Raw/canonical domains and actual transport-shaped fixtures, never authority."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import capture_hash_contract as contract
import remote_preflight_capture as capture

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
OPERATION = 'SYNTHETIC-CAPTURE-HASH-ONLY'

def payload():
    return {'status': 'PASS', 'operation_id': OPERATION, 'mode': 'preflight',
        'claim_absent': True, 'candidate_staged': False, 'production_mutation': False,
        'business_system_write': False, 'raw_secrets_accounts_keys_values_or_pii_emitted': False,
        'text': 'Tiếng Việt: café e\u0301; "quote" \\ slash\nline\tand\u0000escaped-null'}

class HashContractTests(unittest.TestCase):
    def test_exact_production_1953_1805_fixture_old_mismatch_new_contract_roundtrip(self):
        raw = (FIXTURES / 'owned_preflight_1953.stdout.bin').read_bytes()
        parsed = contract.parse_payload(raw)
        semantic = contract.parse_payload((FIXTURES / 'owned_preflight_payload.json').read_bytes())
        legacy = (FIXTURES / 'owned_preflight_1805.legacy.json').read_bytes()
        self.assertEqual(len(raw), 1953)
        self.assertEqual(len(legacy), 1805)
        self.assertEqual(legacy, json.dumps(parsed, sort_keys=True).encode() + b'\n')
        self.assertNotEqual(contract.raw_digest(raw), contract.raw_digest(legacy))
        self.assertEqual(contract.verify_stdout(raw, semantic, contract.stdout_hashes(raw)), parsed)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), '0140bfe2364271a69b96df1e225044e115b47ac795217a35c79daeb0bf60f000')

    def test_lf_crlf_trailing_newline_and_json_layout_preserve_distinct_raw_same_semantics(self):
        value = payload()
        pretty = json.dumps(value, indent=2, ensure_ascii=False).encode('utf-8')
        variants = [pretty, pretty + b'\n', pretty + b'\r\n', pretty.replace(b'\n', b'\r\n'),
            json.dumps(value, ensure_ascii=True).encode(), contract.canonical_bytes(value)]
        self.assertEqual(len({contract.raw_digest(raw) for raw in variants}), len(variants))
        for raw in variants:
            with self.subTest(raw=raw):
                self.assertEqual(contract.verify_stdout(raw, value, contract.stdout_hashes(raw)), value)
                self.assertEqual(contract.stdout_hashes(raw)['canonical_payload_sha256'], contract.canonical_digest(value))

    def test_deterministic_key_order_and_escaped_unicode(self):
        a = {'b': {'z': 1, 'a': 'café'}, 'a': [True, 2]}
        b = {'a': [True, 2], 'b': {'a': 'café', 'z': 1}}
        self.assertEqual(contract.canonical_bytes(a), contract.canonical_bytes(b))
        self.assertEqual(contract.canonical_digest(a), contract.canonical_digest(b))
        self.assertEqual(contract.parse_payload(json.dumps(a).encode()), a)

    def test_unicode_codepoints_never_normalized(self):
        self.assertNotEqual(contract.canonical_digest({'text': 'é'}), contract.canonical_digest({'text': 'e\u0301'}))

    def test_canonical_domain_is_separate_even_when_raw_is_already_compact(self):
        value = {'a': 1}
        raw = contract.canonical_bytes(value)
        digests = contract.stdout_hashes(raw)
        self.assertNotEqual(digests['raw_stdout_sha256'], digests['canonical_payload_sha256'])
        self.assertEqual(digests['canonical_payload_sha256'], hashlib.sha256(contract.CANONICAL_DOMAIN + raw).hexdigest())

    def test_changed_byte_truncated_output_and_missing_raw_fail(self):
        value = payload(); raw = contract.canonical_bytes(value); receipt = contract.stdout_hashes(raw)
        for changed in (raw.replace(b'PASS', b'FAIL'), raw[:-1], b'', None, raw.decode()):
            with self.subTest(changed=changed), self.assertRaises(contract.CaptureHashError):
                contract.verify_stdout(changed, value, receipt)

    def test_modified_semantic_object_and_bool_integer_substitution_fail(self):
        value = {'a': True}; raw = b'{"a":true}'; receipt = contract.stdout_hashes(raw)
        for changed in ({'a': False}, {'a': 1}):
            with self.assertRaises(contract.CaptureHashError): contract.verify_stdout(raw, changed, receipt)

    def test_swapped_wrong_type_wrong_domain_or_missing_digest_fail(self):
        value = payload(); raw = contract.canonical_bytes(value); receipt = contract.stdout_hashes(raw)
        changes = [{'raw_stdout_sha256': receipt['canonical_payload_sha256']},
            {'canonical_payload_sha256': receipt['raw_stdout_sha256']}, {'raw_stdout_sha256': 1},
            {'canonical_payload_sha256': None}, {'hash_contract': 'legacy'}, {'raw_stdout_length_bytes': len(raw) - 1}]
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises(contract.CaptureHashError):
                contract.verify_stdout(raw, value, {**receipt, **changed})

    def test_invalid_utf8_bom_utf16_surrogates_duplicates_null_and_nonfinite_fail(self):
        for raw in (b'\xff', b'\xef\xbb\xbf{}', '{}'.encode('utf-16'), b'{"a":"\\ud800"}',
            b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{}\0', b'{}{}', b'[]'):
            with self.subTest(raw=raw), self.assertRaises(contract.CaptureHashError): contract.parse_payload(raw)

    def test_stream_hashes_empty_and_nonempty_stderr_are_independent(self):
        raw = b'{"a":1}'
        for stderr in (b'', 'Unicode diagnostic: lỗi\r\n'.encode()):
            self.assertEqual(capture._stream(stderr)['sha256'], hashlib.sha256(stderr).hexdigest())
            self.assertEqual(contract.stdout_hashes(raw)['raw_stdout_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertNotEqual(contract.raw_digest(raw), contract.raw_digest(raw + stderr) if stderr else contract.raw_digest(stderr))

class RawCustodyProducerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def invoke(self, raw, *, stderr=b'', code=0, verifier=lambda value: True):
        return capture.invoke_preflight(lambda argv, **kw: subprocess.CompletedProcess(argv, code, raw, stderr),
            ['never-launched'], input_bytes=b'fixture-only', timeout=1, evidence_directory=self.root,
            binding_id=OPERATION, success_verifier=verifier, retain_raw_stdout=True)

    def test_verified_success_publishes_exact_raw_bytes_after_verifier_and_receipt_first(self):
        raw = json.dumps(payload(), ensure_ascii=False, indent=2).encode() + b'\r\n'
        def verifier(value):
            self.assertEqual(len(list(self.root.glob('capture-*.json'))), 1)
            self.assertFalse(list(self.root.glob('*.bin')))
            return True
        value, path = self.invoke(raw, verifier=verifier)
        receipt = json.loads(path.read_bytes())
        self.assertEqual(receipt['schema'], contract.CAPTURE_SCHEMA)
        self.assertEqual((self.root / receipt['raw_stdout_file']).read_bytes(), raw)
        contract.verify_stdout(raw, value, receipt)

    def test_invalid_sensitive_opaque_or_stderr_failure_never_archives_raw_success(self):
        for raw, stderr, code in ((b'opaque private output', b'', 0),
            (json.dumps(payload()).encode(), b'warning', 0), (json.dumps(payload()).encode(), b'', 2)):
            with self.assertRaises(capture.CaptureStop): self.invoke(raw, stderr=stderr, code=code)
        self.assertFalse(list(self.root.glob('*.bin')))

    def test_rejected_verifier_never_archives_raw_success(self):
        with self.assertRaises(capture.CaptureStop): self.invoke(json.dumps(payload()).encode(), verifier=lambda value: False)
        self.assertFalse(list(self.root.glob('*.bin')))

    def test_text_mode_transport_is_not_raw_custody(self):
        with self.assertRaisesRegex(capture.CaptureStop, 'RAW_BYTES_REQUIRED'):
            self.invoke(json.dumps(payload()))
        receipt = json.loads(next(self.root.glob('capture-*.json')).read_bytes())
        self.assertFalse(receipt['raw_transport_bytes'])
        self.assertIsNone(receipt['raw_stdout_sha256'])
        self.assertFalse(list(self.root.glob('*.bin')))

    def test_raw_publication_failure_is_fail_closed_after_receipt(self):
        with patch.object(capture, '_publish_raw_stdout', side_effect=OSError('fixture-only')):
            with self.assertRaises(capture.CaptureStop) as error: self.invoke(json.dumps(payload()).encode())
        self.assertEqual(error.exception.reason, 'CAPTURE_EVIDENCE_UNAVAILABLE')
        self.assertTrue(error.exception.capture_path.is_file())

    def test_actual_binary_subprocess_pipe_preserves_unicode_crlf_and_both_streams(self):
        raw = json.dumps(payload(), ensure_ascii=False, indent=2).encode() + b'\r\n'
        def invoker(argv, *, input_bytes, timeout):
            return subprocess.run([sys.executable, '-B', '-c',
                'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'], input=input_bytes,
                capture_output=True, shell=False, timeout=timeout)
        value, path = capture.invoke_preflight(invoker, [], input_bytes=raw, timeout=5,
            evidence_directory=self.root, binding_id=OPERATION, success_verifier=lambda value: True,
            retain_raw_stdout=True)
        receipt = json.loads(path.read_bytes())
        self.assertEqual((self.root / receipt['raw_stdout_file']).read_bytes(), raw)
        self.assertEqual(receipt['raw_stderr_sha256'], contract.raw_digest(b''))
        self.assertEqual(value, payload())

if __name__ == '__main__': unittest.main()
