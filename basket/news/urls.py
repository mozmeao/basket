import uuid

from django.urls import path, register_converter

from .views import (
    common_voice_goals,
    confirm,
    custom_unsub_reason,
    list_newsletters,
    lookup_user,
    newsletters,
    send_recovery_message,
    subscribe,
    unsubscribe,
    user,
    user_meta,
)


class UUIDConverter:
    regex = r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}"

    def to_python(self, value):
        return uuid.UUID(value)

    def to_url(self, value):
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(uuid.UUID(value))


register_converter(UUIDConverter, "uuidconverter")

urlpatterns = (
    path("common-voice-goals/", common_voice_goals),
    path("subscribe/", subscribe, name="subscribe"),
    path("unsubscribe/<uuidconverter:token>/", unsubscribe, name="unsubscribe"),
    path("user/<uuidconverter:token>/", user, name="user"),
    path("user-meta/<uuidconverter:token>/", user_meta),
    path("confirm/<uuidconverter:token>/", confirm),
    path("lookup-user/", lookup_user, name="lookup_user"),
    path("recover/", send_recovery_message, name="send_recovery_message"),
    path("custom_unsub_reason/", custom_unsub_reason),
    path("newsletters/", newsletters, name="newsletters_api"),
    path("", list_newsletters),
)
