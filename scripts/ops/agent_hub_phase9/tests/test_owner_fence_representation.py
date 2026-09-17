"""The Owner-fence package may reorder only producer-declared set-like fields."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from owner_fence_representation import (  # noqa: E402
    MOUNT_DESTINATIONS,
    canonical_compose_volumes,
    canonical_docker_mounts,
    effective_topology,
    semantic_topology_digest,
)


def mounts():
    return [
        {"Type": "bind", "Source": "/etc/npd-ai/ga4-agent-hub-readonly.json",
         "Destination": "/run/secrets/ga4-service-account.json", "Mode": "ro",
         "RW": False, "Propagation": "rprivate"},
        {"Type": "bind", "Source": "/etc/npd-ai/agent-attribution-verification-keys.json",
         "Destination": "/run/secrets/agent-attribution-verification-keys.json",
         "Mode": "", "RW": False, "Propagation": "rprivate"},
    ]


def item():
    return {"Id": "a" * 64, "HostConfig": {"OomKillDisable": None,
            "MaskedPaths": ["/proc/asound", "/proc/acpi"]},
            "Mounts": mounts(), "NetworkSettings": {"Networks": {
                "network": {"Aliases": ["npd-agent-hub", "a" * 64], "IPAMConfig": None}}}}


class RepresentationTests(unittest.TestCase):
    def test_distinct_mount_order_is_nonsemantic(self):
        original = mounts()
        self.assertEqual(set(row["Destination"] for row in original), MOUNT_DESTINATIONS)
        self.assertEqual(canonical_docker_mounts(original, target=True),
                         canonical_docker_mounts(list(reversed(original)), target=True))
        first = item()
        second = copy.deepcopy(first)
        second["Mounts"].reverse()
        self.assertEqual(semantic_topology_digest(first), semantic_topology_digest(second))

    def test_full_mount_record_tamper_denied(self):
        baseline = canonical_docker_mounts(mounts(), target=True)
        for field, value in (("Source", "/dev/null"), ("Source", "/different"),
                             ("Destination", "/run/secrets/other.json"),
                             ("RW", True), ("Mode", "rw"),
                             ("Propagation", "rshared")):
            changed = mounts()
            changed[0][field] = value
            with self.subTest(field=field, value=value):
                try:
                    observed = canonical_docker_mounts(changed, target=True)
                except ValueError:
                    continue
                self.assertNotEqual(observed, baseline)

    def test_duplicate_overlap_missing_extra_denied(self):
        for rows in (
            mounts() + [copy.deepcopy(mounts()[0])],
            mounts() + [dict(mounts()[0], Destination="/run/secrets/ga4-service-account.json/sub")],
            mounts()[:1],
            mounts() + [dict(mounts()[0], Destination="/run/secrets/extra.json")],
        ):
            with self.assertRaises(ValueError):
                canonical_docker_mounts(rows, target=True)

    def test_compose_options_are_exact_and_order_is_not(self):
        volumes = [
            {"type": "bind", "source": mounts()[0]["Source"],
             "target": mounts()[0]["Destination"], "read_only": True,
             "bind": {"create_host_path": True}},
            {"type": "bind", "source": mounts()[1]["Source"],
             "target": mounts()[1]["Destination"], "read_only": True,
             "bind": {}},
        ]
        baseline = canonical_compose_volumes(volumes)
        self.assertEqual(baseline, canonical_compose_volumes(list(reversed(volumes))))
        changed = copy.deepcopy(volumes)
        changed[0]["bind"]["create_host_path"] = False
        self.assertNotEqual(baseline, canonical_compose_volumes(changed))

    def test_order_sensitive_host_config_and_only_oom_default(self):
        first = item()
        changed = copy.deepcopy(first)
        changed["HostConfig"]["MaskedPaths"].reverse()
        self.assertNotEqual(semantic_topology_digest(first), semantic_topology_digest(changed))
        topology = {"host_config": {"OomKillDisable": None}, "mounts": [], "networks": {}}
        self.assertEqual(effective_topology(topology)["host_config"]["OomKillDisable"], False)
        topology["host_config"]["OomKillDisable"] = True
        with self.assertRaises(ValueError):
            effective_topology(topology)


if __name__ == "__main__":
    unittest.main()
