import json
from pathlib import Path

import pytest

from services.api.telemetry_catalog import EVENT_CATALOG, TELEMETRY_SERVICE


SCHEMAS_PATH = Path(__file__).resolve().parents[1] / "docs" / "telemetry" / "event-schemas.json"


def load_event_definitions() -> dict[str, dict]:
    definitions = json.loads(SCHEMAS_PATH.read_text(encoding="utf-8"))["definitions"]
    return {name: schema for name, schema in definitions.items() if "x-level" in schema}


EVENT_DEFINITIONS = load_event_definitions()


def test_catalog_has_exactly_the_events_of_the_contract():
    assert len(EVENT_DEFINITIONS) == 20
    assert set(EVENT_CATALOG) == set(EVENT_DEFINITIONS)


@pytest.mark.parametrize("event_type", sorted(EVENT_DEFINITIONS))
def test_catalog_entry_matches_event_schema(event_type: str):
    schema = EVENT_DEFINITIONS[event_type]
    contract = EVENT_CATALOG[event_type]
    allowlist = schema["allOf"][1]["properties"]["properties"]["properties"]

    assert contract.level == schema["x-level"]
    assert contract.value_property == schema.get("x-value-property")
    assert contract.allowed_properties == frozenset(allowlist)
    assert contract.summary == schema["description"]


def test_value_property_is_always_in_the_allowlist():
    for event_type, contract in EVENT_CATALOG.items():
        if contract.value_property is not None:
            assert contract.value_property in contract.allowed_properties, event_type


def test_service_is_backoffice():
    assert TELEMETRY_SERVICE == "backoffice"
