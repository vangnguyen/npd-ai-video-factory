"""An explicit local in-memory store for API integration fixtures.

Factory defaults remain inactive. This fixture supplies no production/archive
authority and restores every shared service store after each test.
"""
import pytest
from npd_agent_hub.store import MemoryHubStore


@pytest.fixture(autouse=True)
def local_api_store():
    from npd_agent_hub.orchestrator import hub
    replacement=MemoryHubStore()
    objects=[hub]
    objects.extend(v for v in vars(hub).values() if hasattr(v,'store'))
    old=[(obj,obj.store) for obj in objects]
    for obj,_ in old:obj.store=replacement
    try:yield
    finally:
        for obj,value in old:obj.store=value
