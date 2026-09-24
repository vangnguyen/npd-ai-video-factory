"""One pinned Windows OpenSSH path. No host-file staging or fallback exists."""
from pathlib import Path
import shlex
import subprocess

from gate_bindings import require, sha, verify_operation_identity


def openssh_file_option(name, value):
    """Render one Windows OpenSSH file option without whitespace splitting.

    Windows OpenSSH parses the text inside ``-o`` again after argv parsing, so
    passing a path with spaces as one argv element is not sufficient.  Keep the
    option value quoted for that second parser and use forward slashes so a
    backslash cannot become an accidental escape.
    """
    require(name in {'UserKnownHostsFile'}, 'SSH_FILE_OPTION_NAME_INVALID')
    require(isinstance(value, str) and len(value) > 0, 'SSH_FILE_OPTION_PATH_INVALID')
    require(not any(char in value for char in ('\x00', '\r', '\n', '"')), 'SSH_FILE_OPTION_PATH_INVALID')
    normalized = value.replace('\\', '/')
    return f'{name}="{normalized}"'

def strict_argv(profile, remote):
    p = profile['transport']
    require((p['host'], p['port'], p['user']) == ('157.10.201.169', 22, 'root'), 'SSH_TARGET_MISMATCH')
    for key in ('ssh_executable', 'scp_executable', 'keygen_executable', 'known_hosts'):
        path = Path(p[key]); require(path.is_file() and not path.is_symlink(), 'SSH_TRUST_FILE_INVALID')
        require(sha(path) == p[key + '_sha256'], 'SSH_TRUST_HASH_MISMATCH')
    key = Path(p['identity_file']); require(key.is_file() and not key.is_symlink(), 'SSH_IDENTITY_PATH_INVALID')
    result = subprocess.run([p['keygen_executable'], '-lf', p['known_hosts']], capture_output=True, shell=False, timeout=15)
    require(result.returncode == 0 and result.stdout.decode().split()[1] == p['host_fingerprint'], 'SSH_HOST_FINGERPRINT_MISMATCH')
    return [p['ssh_executable'], '-F', 'NUL', '-i', p['identity_file'],
        '-o', 'StrictHostKeyChecking=yes', '-o', openssh_file_option('UserKnownHostsFile', p['known_hosts_client_path']),
        '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
        '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2', '-p', '22',
        'root@157.10.201.169', shlex.join(remote)]

def invoke(argv, *, input_bytes=None, timeout=90):
    return subprocess.run(argv, input=input_bytes, capture_output=True, shell=False, timeout=timeout)

def stage_argv(profile, candidate, operation):
    # Check before claim; repeat pinned trust checks immediately before SCP.
    verify_operation_identity(operation)
    require(operation == profile.get('operation_id'), 'STAGE_OPERATION_BINDING_MISMATCH')
    strict_argv(profile, ['true']) # Reverify the same pinned trust, without dispatching.
    p = profile['transport']
    destination = '/var/lib/npd-ai/agent-hub-deployments/phase9-limited-pilot/attempts/' + operation + '/candidate.oci.tar'
    return [p['scp_executable'], '-F', 'NUL', '-i', p['identity_file'], '-P', '22',
        '-o', 'StrictHostKeyChecking=yes', '-o', openssh_file_option('UserKnownHostsFile', p['known_hosts_client_path']),
        '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', str(candidate),
        'root@157.10.201.169:' + destination]
