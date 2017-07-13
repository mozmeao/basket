from django.apps import AppConfig


class BasketNewsConfig(AppConfig):
    def ready(self):
        # This will make sure the app is always imported when
        # Django starts so that shared_task will use this app.
        import basket.news.celery  # noqa
