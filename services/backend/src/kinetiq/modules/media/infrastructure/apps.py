from django.apps import AppConfig


class MediaConfig(AppConfig):
    name = "kinetiq.modules.media.infrastructure"
    label = "kinetiq_media"
    verbose_name = "Kinetiq Media"

    def ready(self) -> None:
        from kinetiq.modules.media.infrastructure import signals  # noqa: F401
