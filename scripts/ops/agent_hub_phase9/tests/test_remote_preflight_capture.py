from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

SOURCE = Path(__file__).resolve().parents[1] / "remote_preflight_capture.py"
SPEC = importlib.util.spec_from_file_location("remote_preflight_capture", SOURCE)
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)
BINDING = "AH-P9-INDEPENDENT-TEST"


def failure(**changes):
    value = {"status": "ABORTED_FAIL_CLOSED", "reason": "PROTECTED_SERVICE_DRIFT",
             "operation_id": BINDING, "raw_sensitive_output": False}
    value.update(changes)
    return json.dumps(value).encode() + b"\r\n"


def success(**changes):
    value = {"status": "PASS", "operation_id": BINDING, "mode": "preflight",
             "claim_absent": True, "candidate_staged": False,
             "production_mutation": False, "business_system_write": False}
    value.update(changes)
    return json.dumps(value).encode()


class CaptureRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def invoke(self, stdout, rc=2, stderr=b"", **options):
        def invoker(argv, *, input_bytes, timeout):
            return subprocess.CompletedProcess(argv, rc, stdout, stderr)
        return capture.invoke_preflight(invoker, ["validated-ssh"], input_bytes=b"fixture",
            timeout=1, evidence_directory=self.directory, binding_id=BINDING, **options)

    def stopped(self, stdout, rc=2, stderr=b"", **options):
        with self.assertRaises(capture.CaptureStop) as caught:
            self.invoke(stdout, rc, stderr, **options)
        self.assertIsNotNone(caught.exception.capture_path)
        receipt = json.loads(caught.exception.capture_path.read_bytes())
        self.assertFalse(list(self.directory.glob(".capture-*")))
        return caught.exception, receipt

    def test_stdout_failure_empty_stderr_retains_exact_bytes_rc_uuid_before_abort(self):
        raw, identifier = failure(), str(uuid4())
        error, receipt = self.stopped(raw, invocation_id=identifier)
        self.assertEqual(error.reason, "REMOTE_PREFLIGHT_FAILED:PROTECTED_SERVICE_DRIFT")
        self.assertEqual(receipt["child_returncode"], 2)
        self.assertEqual(receipt["invocation_id"], identifier)
        self.assertEqual(base64.b64decode(receipt["stdout"]["base64"]), raw)
        self.assertEqual(receipt["stdout"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt["stderr"]["length_bytes"], 0)
        self.assertEqual(receipt["stderr"]["sha256"], hashlib.sha256(b"").hexdigest())

    def test_pass_with_nonzero_exit_never_returns_success(self):
        error, receipt = self.stopped(success())
        self.assertEqual(error.reason, "REMOTE_PREFLIGHT_FAILED:UNCLASSIFIED")
        self.assertEqual(receipt["child_returncode"], 2)

    def test_failure_with_zero_exit_never_returns_success(self):
        error, receipt = self.stopped(failure(), rc=0)
        self.assertEqual(error.reason, "REMOTE_PREFLIGHT_OUTPUT_INVALID")
        self.assertEqual(receipt["child_returncode"], 0)

    def test_valid_readonly_success_has_persisted_receipt(self):
        value, path = self.invoke(success(), rc=0)
        self.assertEqual(value["status"], "PASS")
        self.assertEqual(json.loads(path.read_bytes())["child_returncode"], 0)

    def test_success_requires_all_readonly_flags(self):
        for field in ("claim_absent", "candidate_staged", "production_mutation", "business_system_write"):
            with self.subTest(field=field):
                error, _ = self.stopped(success(**{field: None}), rc=0)
                self.assertEqual(error.reason, "REMOTE_PREFLIGHT_OUTPUT_INVALID")

    def test_success_rejects_wrong_binding_or_mode(self):
        for changes in ({"operation_id": "OTHER"}, {"mode": "deploy"}):
            with self.subTest(changes=changes):
                error, _ = self.stopped(success(**changes), rc=0)
                self.assertEqual(error.reason, "REMOTE_PREFLIGHT_OUTPUT_INVALID")

    def test_empty_stdout_is_unclassified_with_exact_receipt(self):
        error, receipt = self.stopped(b"")
        self.assertEqual(error.reason, "REMOTE_PREFLIGHT_FAILED:UNCLASSIFIED")
        self.assertEqual(receipt["stdout"]["content"], "EMPTY")

    def test_opaque_stderr_is_hashed_and_never_written_verbatim(self):
        private = b"fixture-only-secret=DO_NOT_PERSIST"
        error, receipt = self.stopped(failure(), stderr=private)
        self.assertEqual(receipt["stderr"]["sha256"], hashlib.sha256(private).hexdigest())
        self.assertEqual(receipt["stderr"]["length_bytes"], len(private))
        self.assertNotIn(private, error.capture_path.read_bytes())
        self.assertNotIn("base64", receipt["stderr"])

    def test_failure_with_extra_sensitive_field_is_not_archived(self):
        raw = failure(token="fixture-only-secret")
        error, receipt = self.stopped(raw)
        self.assertIsNone(receipt["validated_failure"])
        self.assertNotIn(b"fixture-only-secret", error.capture_path.read_bytes())
        self.assertNotIn("base64", receipt["stdout"])

    def test_unapproved_reason_or_binding_or_sensitive_flag_is_redacted(self):
        for changes in ({"reason": "fixture-only-secret"}, {"operation_id": "OTHER"},
                        {"raw_sensitive_output": True}, {"reason": []}):
            with self.subTest(changes=changes):
                error, receipt = self.stopped(failure(**changes))
                self.assertEqual(error.reason, "REMOTE_PREFLIGHT_FAILED:UNCLASSIFIED")
                self.assertIsNone(receipt["validated_failure"])
                self.assertNotIn("base64", receipt["stdout"])

    def test_duplicate_keys_invalid_utf8_multiple_documents_and_arrays_are_rejected(self):
        duplicate = failure().replace(b'"PROTECTED_SERVICE_DRIFT"',
            b'"PROTECTED_SERVICE_DRIFT", "reason": "PROTECTED_SERVICE_DRIFT"')
        for raw in (duplicate, b"\xff", failure() + b"{}", b"[]"):
            with self.subTest(raw=raw):
                error, receipt = self.stopped(raw)
                self.assertEqual(error.reason, "REMOTE_PREFLIGHT_FAILED:UNCLASSIFIED")
                self.assertIsNone(receipt["validated_failure"])

    def test_invocation_collision_never_overwrites_receipt(self):
        identifier = str(uuid4())
        first, _ = self.stopped(failure(), invocation_id=identifier)
        original = first.capture_path.read_bytes()
        with self.assertRaises(capture.CaptureStop) as caught:
            self.invoke(success(), rc=0, invocation_id=identifier)
        self.assertEqual(caught.exception.reason, "CAPTURE_EVIDENCE_UNAVAILABLE")
        self.assertEqual(first.capture_path.read_bytes(), original)
        self.assertFalse(list(self.directory.glob(".capture-*")))

    def test_capture_write_failure_never_returns_success(self):
        self.directory = self.directory / "regular-file"
        self.directory.write_bytes(b"immutable")
        with self.assertRaises(capture.CaptureStop) as caught:
            self.invoke(success(), rc=0)
        self.assertEqual(caught.exception.reason, "CAPTURE_EVIDENCE_UNAVAILABLE")

    def test_timeout_preserves_partial_streams_and_distinct_status(self):
        def invoker(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 1, output=failure(), stderr=b"opaque")
        with self.assertRaises(capture.CaptureStop) as caught:
            capture.invoke_preflight(invoker, ["validated-ssh"], input_bytes=b"fixture", timeout=1,
                evidence_directory=self.directory, binding_id=BINDING)
        receipt = json.loads(caught.exception.capture_path.read_bytes())
        self.assertEqual(caught.exception.reason, "REMOTE_PREFLIGHT_TIMEOUT")
        self.assertTrue(receipt["timed_out"])
        self.assertIsNone(receipt["child_returncode"])
        self.assertEqual(receipt["stdout"]["length_bytes"], len(failure()))

    def test_launch_error_is_persisted_without_exception_message(self):
        def invoker(argv, **kwargs):
            raise FileNotFoundError("fixture-only-secret")
        with self.assertRaises(capture.CaptureStop) as caught:
            capture.invoke_preflight(invoker, ["validated-ssh"], input_bytes=b"fixture", timeout=1,
                evidence_directory=self.directory, binding_id=BINDING)
        raw = caught.exception.capture_path.read_bytes()
        self.assertNotIn(b"fixture-only-secret", raw)
        self.assertEqual(json.loads(raw)["launch_error_class"], "FileNotFoundError")

    def test_existing_transport_wrapped_timeout_preserves_partial_streams(self):
        def invoker(argv, **kwargs):
            try:
                raise subprocess.TimeoutExpired(argv, 1, output=failure(), stderr=b"opaque")
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("LOCAL_VALIDATION_COMMAND_TIMEOUT") from error
        with self.assertRaises(capture.CaptureStop) as caught:
            capture.invoke_preflight(invoker, ["validated-ssh"], input_bytes=b"fixture", timeout=1,
                evidence_directory=self.directory, binding_id=BINDING)
        receipt = json.loads(caught.exception.capture_path.read_bytes())
        self.assertEqual(caught.exception.reason, "REMOTE_PREFLIGHT_TIMEOUT")
        self.assertTrue(receipt["timed_out"])
        self.assertEqual(receipt["stdout"]["length_bytes"], len(failure()))

    def test_existing_transport_wrapped_start_error_is_redacted_and_captured(self):
        def invoker(argv, **kwargs):
            try:
                raise FileNotFoundError("fixture-only-secret")
            except OSError as error:
                raise RuntimeError("LOCAL_VALIDATION_COMMAND_START_FAILED") from error
        with self.assertRaises(capture.CaptureStop) as caught:
            capture.invoke_preflight(invoker, ["validated-ssh"], input_bytes=b"fixture", timeout=1,
                evidence_directory=self.directory, binding_id=BINDING)
        raw = caught.exception.capture_path.read_bytes()
        self.assertEqual(json.loads(raw)["launch_error_class"], "FileNotFoundError")
        self.assertNotIn(b"fixture-only-secret", raw)

    def test_uuid_and_binding_are_validated_before_child_invocation(self):
        for identifier, binding in (("../escape", BINDING), (str(uuid4()), "unsafe\nvalue")):
            def forbidden(*args, **kwargs):
                self.fail("child must not run")
            with self.assertRaises(capture.CaptureStop) as caught:
                capture.invoke_preflight(forbidden, [], input_bytes=b"", timeout=1,
                    evidence_directory=self.directory, binding_id=binding, invocation_id=identifier)
            self.assertEqual(caught.exception.reason, "CAPTURE_BINDING_INVALID")
        self.assertFalse(list(self.directory.iterdir()))

    def test_actual_local_subprocess_reproduces_remote_stdout_exit_two(self):
        program = "import sys; sys.stdout.buffer.write(" + repr(failure()) + "); raise SystemExit(2)"
        def invoker(argv, *, input_bytes, timeout):
            return subprocess.run(argv, input=input_bytes, capture_output=True, timeout=timeout, shell=False)
        with self.assertRaises(capture.CaptureStop) as caught:
            capture.invoke_preflight(invoker, [sys.executable, "-B", "-c", program], input_bytes=b"", timeout=5,
                evidence_directory=self.directory, binding_id=BINDING)
        receipt = json.loads(caught.exception.capture_path.read_bytes())
        self.assertEqual(caught.exception.reason, "REMOTE_PREFLIGHT_FAILED:PROTECTED_SERVICE_DRIFT")
        self.assertEqual(receipt["child_returncode"], 2)
        self.assertEqual(receipt["stderr"]["length_bytes"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
