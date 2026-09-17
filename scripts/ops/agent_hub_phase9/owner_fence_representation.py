"""Shared, fail-closed representation rules for the Phase 9 Owner-fence gate.

The package builder embeds these exact bytes in both remote entrypoints.  Docker
mount array order is not authority: the complete records are keyed by unique,
non-overlapping destinations.  Every other array retains its sealed order unless
an explicit producer rule below says otherwise.
"""

import copy
import hashlib
import json


MOUNT_DESTINATIONS = frozenset({
    "/run/secrets/ga4-service-account.json",
    "/run/secrets/agent-attribution-verification-keys.json",
})

REPRESENTATION_REGISTRY = {
    "docker.Mounts": "ORDER_INSENSITIVE_CANONICALIZED_BY_DESTINATION_FULL_RECORD",
    "compose.services.agent-hub.volumes": "ORDER_INSENSITIVE_CANONICALIZED_BY_TARGET_FULL_RECORD",
    "docker.NetworkSettings.Networks": "ORDER_INSENSITIVE_OBJECT_KEYS",
    "docker.NetworkSettings.Networks.*.Aliases": "ORDER_INSENSITIVE_FILTERED_SET",
    "docker.HostConfig.Binds": "ORDER_SENSITIVE_EXACT",
    "docker.HostConfig.Mounts": "ORDER_SENSITIVE_EXACT",
    "docker.HostConfig.MaskedPaths": "ORDER_SENSITIVE_EXACT",
    "docker.HostConfig.ReadonlyPaths": "ORDER_SENSITIVE_EXACT",
    "docker.HostConfig.PortBindings.*": "ORDER_SENSITIVE_EXACT",
    "docker.Config.Cmd": "ORDER_SENSITIVE_EXACT",
    "docker.Config.Entrypoint": "ORDER_SENSITIVE_EXACT",
    "docker.Config.Env": "ORDER_INSENSITIVE_UNIQUE_NAME_MAP",
    "docker.Config.Labels": "ORDER_INSENSITIVE_OBJECT_KEYS",
    "compose.file_paths": "ORDER_SENSITIVE_EXACT_OVERRIDE_PRECEDENCE",
    "compose.service_dependencies": "ORDER_SENSITIVE_EXACT_IF_SEQUENCE",
    "protected.services": "ORDER_INSENSITIVE_NAME_KEYED_MAP_WITH_STRICT_VALUES",
    "db1.keyset": "ORDER_INSENSITIVE_SORTED_BYTE_KEYS",
    "db1.indexed_audit": "ORDER_SENSITIVE_EXACT",
    "package.source_hashes": "ORDER_INSENSITIVE_PATH_KEYED_MAP",
    "package.manifest_entries": "ORDER_INSENSITIVE_PATH_KEYED_MAP",
    "gate.operation_bindings": "SCALAR_EXACT",
    "docker.HostConfig.OomKillDisable": "SCALAR_SPECIAL_NULL_MISSING_FALSE_ONLY",
}


def _deny(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(right.rstrip("/") + "/") or right.startswith(left.rstrip("/") + "/")


def _canonical_records(rows: object, destination_key: str, *, expected: frozenset[str] | None = None) -> list[dict]:
    _deny(isinstance(rows, list), "MOUNT_COLLECTION_INVALID")
    result: list[dict] = []
    destinations: list[str] = []
    for row in rows:
        _deny(isinstance(row, dict), "MOUNT_RECORD_INVALID")
        destination = row.get(destination_key)
        _deny(isinstance(destination, str) and destination.startswith("/") and destination != "/", "MOUNT_DESTINATION_INVALID")
        _deny(destination not in destinations, "MOUNT_DUPLICATE_DESTINATION")
        _deny(not any(_overlap(destination, prior) for prior in destinations), "MOUNT_OVERLAPPING_DESTINATION")
        destinations.append(destination)
        result.append(copy.deepcopy(row))
    if expected is not None:
        _deny(set(destinations) == expected and len(destinations) == len(expected), "MOUNT_DESTINATION_SET_DRIFT")
    return sorted(result, key=lambda row: row[destination_key])


def canonical_docker_mounts(rows: object, *, target: bool = False) -> list[dict]:
    result = _canonical_records(rows, "Destination", expected=MOUNT_DESTINATIONS if target else None)
    if target:
        for row in result:
            _deny(row.get("Type") == "bind", "TARGET_MOUNT_TYPE_DRIFT")
            _deny(isinstance(row.get("Source"), str) and row["Source"] != "/dev/null", "TARGET_MOUNT_SOURCE_INVALID")
            _deny(row.get("RW") is False, "TARGET_MOUNT_NOT_READ_ONLY")
            _deny(isinstance(row.get("Mode"), str) and isinstance(row.get("Propagation"), str), "TARGET_MOUNT_OPTIONS_INVALID")
    return result


def canonical_compose_volumes(rows: object) -> list[dict]:
    result = _canonical_records(rows, "target", expected=MOUNT_DESTINATIONS)
    for row in result:
        _deny(row.get("type") == "bind", "COMPOSE_MOUNT_TYPE_DRIFT")
        _deny(isinstance(row.get("source"), str) and row["source"] != "/dev/null", "COMPOSE_MOUNT_SOURCE_INVALID")
        _deny(row.get("read_only") is True, "COMPOSE_MOUNT_NOT_READ_ONLY")
    return result


def canonical_network_aliases(aliases: object, identifier: str) -> list[str]:
    _deny(isinstance(aliases, list), "NETWORK_ALIASES_INVALID")
    remaining = [value for value in aliases if value not in (identifier, identifier[:12])]
    _deny(all(isinstance(value, str) for value in remaining) and len(remaining) == len(set(remaining)), "NETWORK_ALIASES_DUPLICATE_OR_INVALID")
    return sorted(remaining)


def semantic_topology(item: dict) -> dict:
    networks = {}
    identifier = str(item.get("Id", ""))
    for name, value in (item.get("NetworkSettings", {}).get("Networks") or {}).items():
        networks[name] = {
            "aliases": canonical_network_aliases(value.get("Aliases") or [], identifier),
            "IPAMConfig": value.get("IPAMConfig"),
        }
    return {
        "host_config": item.get("HostConfig"),
        "mounts": canonical_docker_mounts(item.get("Mounts") or [], target=True),
        "networks": networks,
    }


def semantic_topology_digest(item: dict) -> str:
    return hashlib.sha256(json.dumps(semantic_topology(item), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def effective_topology(value: dict) -> dict:
    result = copy.deepcopy(value)
    host = result.get("host_config")
    _deny(isinstance(host, dict), "TOPOLOGY_HOST_CONFIG_MISSING")
    raw = host.get("OomKillDisable")
    _deny(raw is None or raw is False, "OOM_KILL_DISABLE_TRUE_OR_INVALID")
    host["OomKillDisable"] = False
    return result


def strict_protected_projection(items: list[dict], project: str, service: str, relevant_pattern) -> dict:
    """Name-keyed service set; only each service's mount order is canonicalized."""
    output = {}
    for item in items:
        config = item.get("Config") or {}
        labels = config.get("Labels") or {}
        if labels.get("com.docker.compose.project") == project and labels.get("com.docker.compose.service") == service:
            continue
        identity = " ".join((str(item.get("Name", "")), str(labels.get("com.docker.compose.project", "")), str(labels.get("com.docker.compose.service", ""))))
        if not relevant_pattern.search(identity):
            continue
        name = str(item.get("Name", "")).lstrip("/")
        _deny(name and name not in output, "PROTECTED_SERVICE_DUPLICATE_NAME")
        state = item.get("State") or {}
        output[name] = {
            "compose_project": labels.get("com.docker.compose.project"),
            "compose_service": labels.get("com.docker.compose.service"),
            "id": item.get("Id"),
            "image_id": item.get("Image"),
            "mounts": canonical_docker_mounts(item.get("Mounts") or []),
            "name": name,
            "networks": sorted((item.get("NetworkSettings", {}).get("Networks") or {}).keys()),
            "ports": (item.get("HostConfig") or {}).get("PortBindings") or {},
            "restart_count": item.get("RestartCount"),
            "running": state.get("Running"),
            "status": state.get("Status"),
            "health": (state.get("Health") or {}).get("Status"),
        }
    return output


def strict_protected_digest(items: list[dict], project: str, service: str, relevant_pattern) -> tuple[str, int]:
    projection = strict_protected_projection(items, project, service, relevant_pattern)
    raw = json.dumps(projection, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest(), len(projection)
