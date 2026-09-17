"""Embed the one sealed representation source into standalone read-only probes."""
from pathlib import Path

root = Path(__file__).resolve().parent
shared = (root / "owner_fence_representation.py").read_text(encoding="utf-8")
marker = "# __SHARED_REPRESENTATION_SOURCE__"
for template_name in ("host_topology_attempt_readonly.py", "strict_protected_readonly.py"):
    source = (root / template_name).read_text(encoding="utf-8")
    if source.count(marker) != 1:
        raise RuntimeError(f"REPRESENTATION_MARKER_CARDINALITY:{template_name}")
    output = root / template_name.replace(".py", ".payload.py")
    rendered = source.replace(marker, shared)
    compile(rendered, str(output), "exec")
    output.write_text(rendered, encoding="utf-8", newline="\n")
