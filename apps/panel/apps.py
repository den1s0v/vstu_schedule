from django.apps import AppConfig


class PanelConfig(AppConfig):
    name = "apps.panel"
    
    def ready(self) -> None:
        """Импорт сигналов при готовности приложения."""
        import apps.panel.signals  # noqa: F401
