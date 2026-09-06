from npd_agent_hub.repositories import HubStore as RepositoryHubStore
from npd_agent_hub.store import HubStore, MemoryHubStore


def test_store_protocol_remains_available_from_legacy_module():
    assert HubStore is RepositoryHubStore


def test_memory_store_still_satisfies_runtime_protocol_surface():
    store = MemoryHubStore()
    required_methods = {
        name
        for name, value in RepositoryHubStore.__dict__.items()
        if callable(value) and not name.startswith("_")
    }
    assert required_methods
    assert all(callable(getattr(store, name, None)) for name in required_methods)
