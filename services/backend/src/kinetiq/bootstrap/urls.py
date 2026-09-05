from django.http import HttpRequest, JsonResponse
from django.urls import path
from strawberry.django.views import AsyncGraphQLView

from kinetiq.interfaces.graphql.schema import schema


def health(_: HttpRequest) -> JsonResponse:
    return JsonResponse({"service": "kinetiq-backend", "status": "ok"})


urlpatterns = [
    path("health/", health, name="health"),
    path("graphql/", AsyncGraphQLView.as_view(schema=schema), name="graphql"),
]
