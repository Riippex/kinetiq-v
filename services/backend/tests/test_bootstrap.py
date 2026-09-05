from django.test import Client, override_settings

from kinetiq.interfaces.graphql.schema import schema


@override_settings(ALLOWED_HOSTS=["testserver"])
def test_health_endpoint_reports_service_ready() -> None:
    response = Client().get("/health/")

    assert response.status_code == 200
    assert response.json() == {"service": "kinetiq-backend", "status": "ok"}


def test_graphql_schema_exposes_service_status() -> None:
    result = schema.execute_sync("{ serviceStatus { name version ready } }")

    assert result.errors is None
    assert result.data == {
        "serviceStatus": {"name": "kinetiq-backend", "version": "0.1.0", "ready": True}
    }
