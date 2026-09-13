"""Explicit raw-byte custody and separately domain-separated JSON semantics.

Raw SHA-256 never decodes, normalizes or reserializes transport bytes. Canonical
JSON is strict UTF-8 without BOM, duplicate keys, nonfinite values or surrogate
code points. It sorts keys, uses compact separators and retains Unicode code
points exactly. Its digest includes CANONICAL_DOMAIN and no final newline.
"""
import hashlib
import json

CAPTURE_SCHEMA = 'npd.agent-hub.phase9.remote-preflight-capture.v2'
HASH_CONTRACT = 'npd.agent-hub.phase9.raw-bytes-and-canonical-json.v1'
CANONICAL_DOMAIN = b'npd.agent-hub.phase9.canonical-payload.v1\x00'
MAX_STDOUT_BYTES = 1024 * 1024


class CaptureHashError(ValueError):
    pass


def raw_digest(raw):
    if type(raw) is not bytes:
        raise CaptureHashError('RAW_BYTES_REQUIRED')
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CaptureHashError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _nonfinite(value):
    raise CaptureHashError('NONFINITE_JSON')


def canonical_bytes(value):
    if not isinstance(value, dict):
        raise CaptureHashError('JSON_OBJECT_REQUIRED')
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(',', ':')).encode('utf-8', errors='strict')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise CaptureHashError('CANONICAL_JSON_INVALID') from None


def canonical_digest(value):
    return hashlib.sha256(CANONICAL_DOMAIN + canonical_bytes(value)).hexdigest()


def parse_payload(raw):
    raw_digest(raw)
    if len(raw) > MAX_STDOUT_BYTES or raw.startswith(b'\xef\xbb\xbf'):
        raise CaptureHashError('JSON_ENCODING_OR_SIZE_INVALID')
    try:
        value = json.loads(raw.decode('utf-8', errors='strict'),
            object_pairs_hook=_unique, parse_constant=_nonfinite)
        canonical_bytes(value)
        return value
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise CaptureHashError('STRICT_UTF8_JSON_INVALID') from None


def stdout_hashes(raw):
    result = {'hash_contract': HASH_CONTRACT, 'raw_stdout_sha256': raw_digest(raw),
        'raw_stdout_length_bytes': len(raw), 'canonical_payload_sha256': None}
    try:
        result['canonical_payload_sha256'] = canonical_digest(parse_payload(raw))
    except CaptureHashError:
        pass
    return result


def verify_stdout(raw, payload, receipt):
    """Verify both digest domains, never substitute semantic bytes for custody."""
    wanted = stdout_hashes(raw)
    if wanted['canonical_payload_sha256'] is None:
        raise CaptureHashError('STRICT_UTF8_JSON_INVALID')
    if any(receipt.get(name) != value for name, value in wanted.items()):
        raise CaptureHashError('CAPTURE_HASH_CONTRACT_MISMATCH')
    if canonical_digest(payload) != wanted['canonical_payload_sha256']:
        raise CaptureHashError('CANONICAL_PAYLOAD_CHANGED')
    return parse_payload(raw)
