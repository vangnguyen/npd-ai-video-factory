"""Load the exact shared SLA contract from a package sidecar or source checkout.

Static/JIT packaging must copy the service's canonical module byte-for-byte
as sales_sla_contract.py and bind its source path and SHA-256 in the manifests.
The source fallback is fixed relative to this file, independent of cwd/PYTHONPATH.
"""
import importlib.util
from pathlib import Path

packaged = Path(__file__).with_name("sales_sla_contract.py")
source = Path(__file__).resolve().parents[3] / "services/agent_hub/npd_agent_hub/sales_sla_contract.py"
path = packaged if packaged.is_file() else source
if not path.is_file() or path.is_symlink():
    raise ImportError("SHARED_SLA_CONTRACT_MISSING_OR_UNSAFE")
spec = importlib.util.spec_from_file_location("phase9_shared_sales_sla_contract", path)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
