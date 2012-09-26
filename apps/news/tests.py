from django import test
from django.http import QueryDict

from mock import patch

from news.models import Subscriber
from news.tasks import SET


class UserTest(test.TestCase):
    @patch('news.views.update_user')
    def test_user_set(self, update_user):
        """If the user view is sent a POST request, it should attempt to update
        the user's info.
        """
        subscriber = Subscriber(email='test@example.com', token='asdf')
        subscriber.save()

        self.client.post('/news/user/asdf/', {'fake': 'data'})
        update_user.assert_called_with(QueryDict('fake=data'),
                                       'test@example.com', SET, True)
