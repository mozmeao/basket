from django.conf import settings
from django.http import HttpResponse

from subscriptions.models import Subscription
from emailer.models import Recipient

def index(request):
    # check that the Firefox Home emails are sending
    s_count = Subscription.objects.filter(campaign='firefox-home-instructions').count()
    r_count = Recipient.objects.filter(email_id='firefox-home-instructions-initial').count()
    delta = s_count - r_count

    if delta > settings.EMAIL_BACKLOG_TOLERANCE:
        return HttpResponseServerError('WARNING: Firefox Home email backlog is %d' % delta)

    return HttpResponse('SUCCESS')

def unsub(request):
    count = Subscription.objects.filter(active=False).count()
    return HttpResponse(count)
