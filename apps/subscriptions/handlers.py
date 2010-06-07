from django.core.exceptions import ValidationError
from django.utils import encoding

from piston.handler import BaseHandler
from piston.utils import rc

from subscriptions.models import Subscription


def validate(model):
    def decorator(target):
        def wrapper(self, request, *args, **kwargs):
            try:
                attrs = self.flatten_dict(request.data)
                m = model(**attrs)
                m.validate_unique()
            except ValidationError, e:
                resp = rc.DUPLICATE_ENTRY
                resp.write(encoding.smart_unicode(e.message_dict))
                return resp

            try:
                m.full_clean()
                target(self, request, *args, **kwargs)
            except ValidationError, e:
                resp = rc.BAD_REQUEST
                resp.write(encoding.smart_unicode(e.message_dict))
                return resp
        return wrapper
    return decorator


class SubscriptionHandler(BaseHandler):
    fields = ('email', 'campaign', 'active', 'source')
    model = Subscription

    @validate(Subscription)
    def create(self, request):
        return BaseHandler.create(self, request)
