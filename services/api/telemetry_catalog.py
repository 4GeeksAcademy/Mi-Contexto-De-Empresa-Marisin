"""Contrato de almacenamiento de cada evento de telemetría (D34).

Réplica en Python de `docs/telemetry/event-schemas.json`: el contenedor de la API
solo monta `services/`, así que el JSON no está disponible en runtime.
`tests/test_telemetry_catalog.py` comprueba que ambos coinciden exactamente.
"""

from dataclasses import dataclass


TELEMETRY_SERVICE = "backoffice"


@dataclass(frozen=True)
class EventContract:
    level: str
    value_property: str | None
    allowed_properties: frozenset[str]
    summary: str


EVENT_CATALOG: dict[str, EventContract] = {
    "api_latency_recorded": EventContract(
        level="info",
        value_property="duration_ms",
        allowed_properties=frozenset(
            {
                "api_endpoint",
                "duration_ms",
                "http_method",
                "sample_rate",
                "status_code",
            }
        ),
        summary="Client-observed duration of an API request, recorded by endpoint template.",
    ),
    "api_request_failed": EventContract(
        level="error",
        value_property="status_code",
        allowed_properties=frozenset(
            {
                "api_endpoint",
                "failure_reason",
                "status_code",
            }
        ),
        summary="HTTP 5xx or network failure from the backoffice; excludes 401, 403 and validation errors.",
    ),
    "direct_stock_edit_rejected": EventContract(
        level="warn",
        value_property="quantity",
        allowed_properties=frozenset(
            {
                "attempted_delta",
                "client_id",
                "country",
                "product_category",
                "product_id",
                "quantity",
                "rejection_reason",
                "warehouse",
            }
        ),
        summary="Direct stock edit rejection; capture remains pending until UI and endpoint exist.",
    ),
    "frontend_error_captured": EventContract(
        level="error",
        value_property=None,
        allowed_properties=frozenset(
            {
                "error_fingerprint",
                "error_source",
                "message",
                "route",
                "stack_frames",
            }
        ),
        summary="Frontend error after sanitizing its message and reducing stack frames to file:line.",
    ),
    "inbound_order_created": EventContract(
        level="info",
        value_property="quantity",
        allowed_properties=frozenset(
            {
                "client_id",
                "country",
                "order_id",
                "product_category",
                "product_id",
                "quantity",
                "warehouse",
            }
        ),
        summary="Inbound order created after the API returns HTTP 201.",
    ),
    "inbound_order_validation_failed": EventContract(
        level="warn",
        value_property="quantity",
        allowed_properties=frozenset(
            {
                "client_id",
                "country",
                "failure_reason",
                "product_category",
                "product_id",
                "quantity",
                "validation_source",
                "warehouse",
            }
        ),
        summary="Inbound order validation failure; current capture is from the frontend API error handler.",
    ),
    "inventory_discrepancy_detected": EventContract(
        level="warn",
        value_property="quantity",
        allowed_properties=frozenset(
            {
                "client_id",
                "counted_quantity",
                "country",
                "detection_source",
                "product_category",
                "product_id",
                "quantity",
                "system_quantity",
                "warehouse",
            }
        ),
        summary="Physical count or audit reports a stock discrepancy; capture remains pending until the workflow exists.",
    ),
    "order_form_abandoned": EventContract(
        level="info",
        value_property="time_in_form_ms",
        allowed_properties=frozenset(
            {
                "fields_completed",
                "last_field_touched",
                "order_kind",
                "time_in_form_ms",
            }
        ),
        summary="An order form with a prior start is abandoned without successful submission.",
    ),
    "order_form_started": EventContract(
        level="info",
        value_property=None,
        allowed_properties=frozenset(
            {
                "order_kind",
            }
        ),
        summary="First interaction with an inbound or outbound order form.",
    ),
    "outbound_order_created": EventContract(
        level="info",
        value_property="quantity",
        allowed_properties=frozenset(
            {
                "client_id",
                "country",
                "exit_type",
                "order_id",
                "product_category",
                "product_id",
                "quantity",
                "warehouse",
            }
        ),
        summary="Outbound order created after the API returns HTTP 201; never includes tracking or recipient data.",
    ),
    "outbound_order_validation_failed": EventContract(
        level="warn",
        value_property="quantity",
        allowed_properties=frozenset(
            {
                "client_id",
                "country",
                "failure_reason",
                "product_category",
                "product_id",
                "quantity",
                "validation_source",
                "warehouse",
            }
        ),
        summary="Outbound order validation failure from the client stock check or API response.",
    ),
    "page_viewed": EventContract(
        level="info",
        value_property=None,
        allowed_properties=frozenset(
            {
                "route",
            }
        ),
        summary="Backoffice route view, using a route template without query parameters.",
    ),
    "route_access_denied": EventContract(
        level="warn",
        value_property=None,
        allowed_properties=frozenset(
            {
                "api_endpoint",
                "reason",
                "route",
            }
        ),
        summary="HTTP 403 or inventory guard redirect. userId is null only for reason no_session.",
    ),
    "session_expired": EventContract(
        level="warn",
        value_property=None,
        allowed_properties=frozenset(
            {
                "api_endpoint",
                "route",
            }
        ),
        summary="A protected API request receives HTTP 401 before the client clears the session.",
    ),
    "stock_threshold_cleared": EventContract(
        level="info",
        value_property="quantity",
        allowed_properties=frozenset(
            {
                "client_id",
                "country",
                "min_threshold",
                "product_category",
                "product_id",
                "quantity",
                "threshold_source",
                "trigger_order_id",
                "warehouse",
            }
        ),
        summary="Stock crosses from below the threshold to at or above it after an inbound order.",
    ),
    "stock_threshold_triggered": EventContract(
        level="warn",
        value_property="quantity",
        allowed_properties=frozenset(
            {
                "client_id",
                "country",
                "min_threshold",
                "product_category",
                "product_id",
                "quantity",
                "threshold_source",
                "trigger_order_id",
                "warehouse",
            }
        ),
        summary="Stock crosses from at or above the threshold to below it after an outbound order.",
    ),
    "user_logged_out": EventContract(
        level="info",
        value_property="session_duration_ms",
        allowed_properties=frozenset(
            {
                "session_duration_ms",
            }
        ),
        summary="Explicit logout before the client removes the token.",
    ),
    "user_login_failed": EventContract(
        level="warn",
        value_property=None,
        allowed_properties=frozenset(
            {
                "failure_reason",
            }
        ),
        summary="Failed authentication; userId is null and no credential is captured.",
    ),
    "user_login_succeeded": EventContract(
        level="info",
        value_property=None,
        allowed_properties=frozenset(
            {
            }
        ),
        summary="Successful backoffice authentication after token storage. Count daily distinct users by opaque userId and compare aggregate successes with login failures to measure adoption and detect access issues. No warehouse dimension.",
    ),
    "web_vital_recorded": EventContract(
        level="info",
        value_property="metric_value",
        allowed_properties=frozenset(
            {
                "metric_name",
                "metric_value",
                "route",
            }
        ),
        summary="Client-side LCP, INP or CLS metric for a route template.",
    ),
}
