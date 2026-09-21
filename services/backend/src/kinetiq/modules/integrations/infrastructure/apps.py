from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "kinetiq.modules.integrations.infrastructure"
    label = "kinetiq_integrations"
