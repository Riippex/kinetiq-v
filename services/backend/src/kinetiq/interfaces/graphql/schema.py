import strawberry


@strawberry.type
class ServiceStatus:
    name: str
    version: str
    ready: bool


@strawberry.type
class Query:
    @strawberry.field
    def service_status(self) -> ServiceStatus:
        return ServiceStatus(name="kinetiq-backend", version="0.1.0", ready=True)


schema = strawberry.Schema(query=Query)
