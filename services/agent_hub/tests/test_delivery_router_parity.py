from npd_agent_hub.main import app


EXPECTED_DELIVERY_ROUTES = {
    ("get", "/api/v1/attribution/deliveries/status"),
    ("get", "/api/v1/attribution/deliveries/receipts"),
    ("get", "/api/v1/attribution/deliveries/dead-letters"),
    ("post", "/api/v1/attribution/deliveries/receipts/verify"),
    ("post", "/api/v1/attribution/deliveries/failures"),
    ("post", "/api/v1/attribution/deliveries"),
    ("get", "/api/v1/attribution/deliveries/heartbeats"),
    ("post", "/api/v1/attribution/deliveries/heartbeats"),
    ("post", "/api/v1/attribution/deliveries/heartbeats/verify"),
}


def test_delivery_router_preserves_method_path_and_response_contracts():
    paths = app.openapi()["paths"]
    actual = {
        (method, path)
        for path, operations in paths.items()
        if path.startswith("/api/v1/attribution/deliveries")
        for method in operations
    }

    assert actual == EXPECTED_DELIVERY_ROUTES
    assert paths["/api/v1/attribution/deliveries/status"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/AttributionDeliveryStatus"
    )
    assert paths["/api/v1/attribution/deliveries/receipts"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]["items"]["$ref"].endswith(
        "/AttributionDeliveryReceipt"
    )
    assert paths["/api/v1/attribution/deliveries/heartbeats"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]["items"]["$ref"].endswith(
        "/AttributionHeartbeatReceipt"
    )


def test_delivery_operation_ids_remain_stable_after_extraction():
    paths = app.openapi()["paths"]
    assert paths["/api/v1/attribution/deliveries/status"]["get"]["operationId"] == (
        "attribution_delivery_status_api_v1_attribution_deliveries_status_get"
    )
    assert paths["/api/v1/attribution/deliveries"]["post"]["operationId"] == (
        "ingest_attribution_delivery_api_v1_attribution_deliveries_post"
    )
    assert paths["/api/v1/attribution/deliveries/heartbeats/verify"]["post"][
        "operationId"
    ] == (
        "verify_attribution_heartbeat_receipt_api_v1_attribution_deliveries_heartbeats_verify_post"
    )
