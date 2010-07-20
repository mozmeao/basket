from django.conf import settings
from django.http import HttpResponse

from subscriptions.models import Subscription
from emailer.models import Email

def index(request):
    # check that the Firefox Home emails are sending
    subscriptions = Subscription.objects.filter(campaign='firefox-home-instructions')
    reg = Email.objects.filter(name='iphone-reg')
    if subscriptions.count() and reg.count():
        delta = subscriptions.count() - reg[0].recipients.count()
        if delta > settings.EMAIL_BACKLOG_TOLERANCE:
            return HttpResponse('ERROR: FxHome email backlog is %d' % delta)

    return HttpResponse('SUCCESS')
