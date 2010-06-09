from django.core.exceptions import ValidationError
from django.utils import encoding

from piston.handler import BaseHandler
from piston.utils import rc

from subscriptions.models import Subscription, Subscriber


class SubscriptionHandler(BaseHandler):
    fields = ('email', 'campaign', 'active', 'source', 'locale')

    def read(self, request):
        return rc.NOT_IMPLEMENTED

    def update(self, request):
        return rc.NOT_IMPLEMENTED

    def delete(self, request):
        return rc.NOT_IMPLEMENTED

    def create(self, request):
        try:
            email = request.data.get('email', '')
            s = Subscriber.objects.get(email=email)
        except Subscriber.DoesNotExist:
            try:
                s = Subscriber(email=email)
                s.full_clean()
                s.save()
            except ValidationError, e:
                resp = rc.BAD_REQUEST
                resp.write(encoding.smart_unicode(e.message_dict))
                return resp

        try:
            campaign = request.data.get('campaign', '')
            source = request.data.get('source', '')
            locale = request.data.get('locale', '')
            m = Subscription(campaign=campaign, source=source, locale=locale)
            m.subscriber = s
            m.validate_unique()
        except ValidationError, e:
            resp = rc.DUPLICATE_ENTRY
            resp.write(encoding.smart_unicode(e.message_dict))
            return resp

        try:
            m.full_clean()
            m.save()
        except ValidationError, e:
            resp = rc.BAD_REQUEST
            resp.write(encoding.smart_unicode(e.message_dict))
            return resp

        return rc.CREATED
