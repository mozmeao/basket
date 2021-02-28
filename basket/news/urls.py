from django.urls import path

from .views import (
    common_voice_goals,
    confirm,
    custom_unsub_reason,
    debug_user,
    fxa_concerts_rsvp,
    get_involved,
    list_newsletters,
    lookup_user,
    newsletters,
    send_recovery_message,
    subscribe,
    sync_route,
    unsubscribe,
    user,
    user_meta,
)


urlpatterns = (
    path("get-involved/", get_involved),
    path("fxa-concerts-rsvp/", fxa_concerts_rsvp),
    path("common-voice-goals/", common_voice_goals),
    path("subscribe/", subscribe),
    path("unsubscribe/<uuid:token>/", unsubscribe),
    path("user/<uuid:token>/", user),
    path("user-meta/<uuid:token>/", user_meta),
    path("confirm/<uuid:token>/", confirm),
    path("debug-user/", debug_user),
    path("lookup-user/", lookup_user, name="lookup_user"),
    path("recover/", send_recovery_message, name="send_recovery_message"),
    path("custom_unsub_reason/", custom_unsub_reason),
    path("newsletters/", newsletters, name="newsletters_api"),
    path("", list_newsletters),
) + sync_route.urlpatterns
