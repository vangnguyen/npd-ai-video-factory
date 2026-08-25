from npd_agent_hub.main import app


EXPECTED_PROVIDER_HEALTH_ROUTES = {
    ("get", "/api/v1/provider-health/status"),
    ("get", "/api/v1/provider-health/scheduler"),
    ("post", "/api/v1/provider-health/evaluate"),
    ("post", "/api/v1/provider-health/refresh"),
    ("get", "/api/v1/provider-health/alerts"),
    (
        "post",
        "/api/v1/provider-health/alerts/{alert_id}/acknowledge",
    ),
}


def test_provider_health_router_preserves_method_path_and_response_contracts():
    paths = app.openapi()["paths"]
    actual = {
        (method, path)
        for path, operations in paths.items()
        if path.startswith("/api/v1/provider-health")
        for method in operations
    }

    assert actual == EXPECTED_PROVIDER_HEALTH_ROUTES
    assert paths["/api/v1/provider-health/status"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"].endswith("/ProviderHealthStatus")
    assert paths["/api/v1/provider-health/scheduler"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"].endswith(
        "/ProviderHealthSchedulerStatus"
    )
    assert paths["/api/v1/provider-health/alerts/{alert_id}/acknowledge"]["post"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ProviderHealthAlert"
    )


def test_provider_health_operation_ids_remain_stable_after_extraction():
    paths = app.openapi()["paths"]
    assert paths["/api/v1/provider-health/status"]["get"]["operationId"] == (
        "provider_health_status_api_v1_provider_health_status_get"
    )
    assert paths["/api/v1/provider-health/evaluate"]["post"]["operationId"] == (
        "evaluate_provider_health_cached_api_v1_provider_health_evaluate_post"
    )
    assert paths["/api/v1/provider-health/alerts/{alert_id}/acknowledge"]["post"][
        "operationId"
    ] == (
        "acknowledge_provider_health_alert_api_v1_provider_health_alerts__alert_id__acknowledge_post"
    )
