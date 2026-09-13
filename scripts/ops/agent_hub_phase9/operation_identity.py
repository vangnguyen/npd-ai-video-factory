"""Canonical pilot identity and legacy v1 wire identifiers.

RCA05/RCA06 are preparation families sharing one dispatch protocol.
Custody parsing never grants execution authority.
"""
from uuid import UUID

SUPPORTED_FAMILIES = ('RCA05', 'RCA06')
DISPATCH_SCHEMA = 'npd.phase9.limited-pilot-rca05.dispatch.v1'
CLAIM_SCHEMA = 'npd.phase9.limited-pilot-rca05.operation-claim.v1'
CONFIRMATION_ENTROPY_PREFIX = 'npd.agent-hub.rca05.confirmation.v1|'
CONSUMED_ABORTED_OPERATION = 'PHASE9-LIMITED-PILOT-RCA06-2da31c5f-b02e-4902-a815-82fa49ee63bc'
RECOVERED_TERMINAL_OPERATION = 'PHASE9-LIMITED-PILOT-RCA06-ae039afa-f715-47f7-8a91-8d536eefc91a'
PREFLIGHT_ABORTED_OPERATION = 'PHASE9-LIMITED-PILOT-RCA06-0936a195-e70a-4189-9434-2a1def050d0a'
RETIRED_EXECUTION_OPERATIONS = frozenset({CONSUMED_ABORTED_OPERATION, RECOVERED_TERMINAL_OPERATION, PREFLIGHT_ABORTED_OPERATION})

class OperationIdentityError(ValueError):
    pass

def parse_operation_id(operation):
    """Only an explicit supported family + lowercase canonical UUID v4."""
    if not isinstance(operation, str):
        raise OperationIdentityError('OPERATION_ID_INVALID')
    prefix = next((f'PHASE9-LIMITED-PILOT-{family}-' for family in SUPPORTED_FAMILIES
                   if operation.startswith(f'PHASE9-LIMITED-PILOT-{family}-')), None)
    if prefix is None:
        raise OperationIdentityError('OPERATION_ID_INVALID')
    suffix = operation[len(prefix):]
    try:
        identifier = UUID(suffix)
    except (ValueError, TypeError, AttributeError):
        raise OperationIdentityError('OPERATION_ID_INVALID') from None
    if str(identifier) != suffix or identifier.version != 4:
        raise OperationIdentityError('OPERATION_ID_INVALID')
    return operation

def validate_fresh_operation_id(operation):
    operation = parse_operation_id(operation)
    if operation in RETIRED_EXECUTION_OPERATIONS:
        raise OperationIdentityError('OPERATION_RETIRED_NOT_REUSABLE')
    return operation
