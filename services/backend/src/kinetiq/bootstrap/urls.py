from django.http import HttpRequest, JsonResponse
from django.urls import path
from strawberry.django.views import GraphQLView

from kinetiq.interfaces.graphql.schema import schema


def health(_: HttpRequest) -> JsonResponse:
    return JsonResponse({"service": "kinetiq-backend", "status": "ok"})


urlpatterns = [
    path("health/", health, name="health"),
    path("graphql/", GraphQLView.as_view(schema=schema), name="graphql"),
]
