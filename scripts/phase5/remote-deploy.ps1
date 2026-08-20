[CmdletBinding()]
param(
    [ValidateSet('Audit', 'Preflight', 'Deploy', 'Caddy', 'LocalSmoke', 'PublicSmoke', 'Rollback', 'CaddyRollback')]
    [string]$Action = 'Audit',
    [string]$VpsHost = '157.10.201.169',
    [string]$SshUser = 'root',
    [string]$SshKeyPath = 'work/n8n-vps/codex_n8n_vps_ed25519',
    [string]$KnownHostsPath = 'work/n8n-vps/known_hosts_test',
    [string]$RepoPath = '/opt/npd-ai-video-factory',
    [string]$ExpectedCommit,
    [string]$AgentHubHostname,
    [string]$RollbackImage,
    [string]$CaddyBackup,
    [string]$Confirm
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$lf = [string][char]10

function Assert-Match {
    param([string]$Name, [string]$Value, [string]$Pattern)
    if ($Value -notmatch $Pattern) {
        throw "$Name contains an unsupported value."
    }
}

function Get-ResolvedUnixPath {
    param([string]$LiteralPath)
    return ((Resolve-Path -LiteralPath $LiteralPath).Path -replace '\\', '/')
}

function Expand-RemoteTemplate {
    param([string]$Template, [hashtable]$Values)
    $result = $Template
    foreach ($name in $Values.Keys) {
        $result = $result.Replace(('__' + $name + '__'), [string]$Values[$name])
    }
    return $result
}

Assert-Match -Name 'VpsHost' -Value $VpsHost -Pattern '^[A-Za-z0-9.-]+$'
Assert-Match -Name 'SshUser' -Value $SshUser -Pattern '^[A-Za-z0-9_-]+$'
Assert-Match -Name 'RepoPath' -Value $RepoPath -Pattern '^/[A-Za-z0-9._/-]+$'

$sshKey = Get-ResolvedUnixPath -LiteralPath $SshKeyPath
$knownHosts = Get-ResolvedUnixPath -LiteralPath $KnownHostsPath
$knownHostsOption = 'UserKnownHostsFile="' + $knownHosts + '"'
$sshArgs = @(
    '-i', $sshKey,
    '-o', $knownHostsOption,
    '-o', 'StrictHostKeyChecking=yes',
    '-o', 'BatchMode=yes',
    "$SshUser@$VpsHost",
    "tr -d '\r' | bash -s"
)

function Invoke-Phase5Remote {
    param([string]$Script)
    $normalized = $Script.Replace([Environment]::NewLine, [string][char]10)
    $normalized | & ssh @sshArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Remote Phase 5 action failed with exit code $LASTEXITCODE."
    }
}

$commonTemplate = @'
set -euo pipefail
REPO_PATH='__REPO_PATH__'
VIDEO_NETWORK='npd-ai-video-factory_default'
N8N_NETWORK='n8n-marketing_n8n_net'
N8N_COMPOSE_FILE='/opt/n8n/docker-compose.yml'
N8N_COMPOSE_PROJECT='n8n-marketing'
CADDY_CONTAINER='n8n-marketing-caddy-1'
CADDYFILE='/opt/n8n/Caddyfile'
'@
$common = Expand-RemoteTemplate -Template $commonTemplate -Values @{ REPO_PATH = $RepoPath }

if ($Action -eq 'Audit') {
    $audit = @'
printf 'host=%s utc=%s\n' "$(hostname)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'repo='; test -d "$REPO_PATH/.git" && echo present || echo missing
if test -d "$REPO_PATH/.git"; then
  git -C "$REPO_PATH" status --short --branch
  git -C "$REPO_PATH" log -1 --format='commit=%H subject=%s'
fi
printf 'agent_hub_env='; if test -f /etc/npd-ai/agent-hub.env; then stat -c 'present mode=%a owner=%U:%G' /etc/npd-ai/agent-hub.env; else echo missing; fi
printf 'port_8010='; if ss -ltnH | awk '{print $4}' | grep -Eq '(^|:)8010$'; then echo listening; else echo free; fi
printf 'video_network_members:\n'
docker network inspect "$VIDEO_NETWORK" --format '{{range .Containers}}{{println .Name}}{{end}}'
printf 'n8n_network_members:\n'
docker network inspect "$N8N_NETWORK" --format '{{range .Containers}}{{println .Name}}{{end}}'
printf 'caddy_mount='; docker inspect "$CADDY_CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{println .Source "->" .Destination .Mode}}{{end}}{{end}}'
docker exec "$CADDY_CONTAINER" caddy validate --config /etc/caddy/Caddyfile >/dev/null
printf 'caddy_validate=ok\n'
'@
    Invoke-Phase5Remote -Script ($common + $lf + $audit)
    exit 0
}

if ([string]::IsNullOrWhiteSpace($ExpectedCommit)) {
    throw 'ExpectedCommit is required for every action except Audit.'
}
Assert-Match -Name 'ExpectedCommit' -Value $ExpectedCommit -Pattern '^[0-9a-fA-F]{40}$'

$guardTemplate = @'
cd "$REPO_PATH"
actual_commit="$(git rev-parse HEAD)"
test "$actual_commit" = '__EXPECTED_COMMIT__' || { echo "remote commit mismatch: expected=__EXPECTED_COMMIT__ actual=$actual_commit" >&2; exit 2; }
git diff --quiet || { echo 'tracked working tree has unstaged changes' >&2; exit 2; }
git diff --cached --quiet || { echo 'tracked working tree has staged changes' >&2; exit 2; }
export AGENT_HUB_ENV_FILE=/etc/npd-ai/agent-hub.env
export NPD_DOCKER_NETWORK="$VIDEO_NETWORK"
export N8N_DOCKER_NETWORK="$N8N_NETWORK"
export N8N_COMPOSE_FILE N8N_COMPOSE_PROJECT
export N8N_CADDY_CONTAINER="$CADDY_CONTAINER"
export N8N_CADDYFILE="$CADDYFILE"
'@
$guard = Expand-RemoteTemplate -Template $guardTemplate -Values @{ EXPECTED_COMMIT = $ExpectedCommit }

if ($Action -eq 'Preflight') {
    Invoke-Phase5Remote -Script ($common + $lf + $guard + $lf + 'bash scripts/phase5/preflight.sh' + $lf)
    exit 0
}

if ($Confirm -ne 'PHASE5_REMOTE_CHANGE') {
    throw 'Mutating/smoke actions require -Confirm PHASE5_REMOTE_CHANGE.'
}

switch ($Action) {
    'Deploy' {
        Invoke-Phase5Remote -Script ($common + $lf + $guard + $lf + 'bash scripts/phase5/deploy.sh' + $lf)
    }
    'Caddy' {
        Assert-Match -Name 'AgentHubHostname' -Value $AgentHubHostname -Pattern '^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$'
        $command = "export AGENT_HUB_HOSTNAME='$AgentHubHostname'" + $lf + 'bash scripts/phase5/caddy-cutover.sh --apply --confirm APPLY_CADDY' + $lf
        Invoke-Phase5Remote -Script ($common + $lf + $guard + $lf + $command)
    }
    'LocalSmoke' {
        $command = 'export AGENT_HUB_PUBLIC_URL=http://127.0.0.1:8010' + $lf + 'bash scripts/phase5/smoke.sh' + $lf
        Invoke-Phase5Remote -Script ($common + $lf + $guard + $lf + $command)
    }
    'PublicSmoke' {
        Assert-Match -Name 'AgentHubHostname' -Value $AgentHubHostname -Pattern '^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$'
        $command = "export AGENT_HUB_PUBLIC_URL='https://$AgentHubHostname'" + $lf + 'bash scripts/phase5/smoke.sh' + $lf
        Invoke-Phase5Remote -Script ($common + $lf + $guard + $lf + $command)
    }
    'Rollback' {
        Assert-Match -Name 'RollbackImage' -Value $RollbackImage -Pattern '^[A-Za-z0-9._/:@-]+$'
        $command = "bash scripts/phase5/rollback.sh --image '$RollbackImage'" + $lf
        Invoke-Phase5Remote -Script ($common + $lf + $guard + $lf + $command)
    }
    'CaddyRollback' {
        Assert-Match -Name 'CaddyBackup' -Value $CaddyBackup -Pattern '^/[A-Za-z0-9._/-]+$'
        $command = "bash scripts/phase5/caddy-cutover.sh --rollback '$CaddyBackup' --confirm ROLLBACK_CADDY" + $lf
        Invoke-Phase5Remote -Script ($common + $lf + $guard + $lf + $command)
    }
    default {
        throw "Unsupported action: $Action"
    }
}
