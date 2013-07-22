from django.test import TestCase

from mock import patch

from news import models


class UpdatePhonebookTest(TestCase):
    def setUp(self):
        self.sub = models.Subscriber.objects.create(email='dude@example.com')
        self.url = '/news/custom_update_phonebook/%s/' % self.sub.token

    @patch('news.views.update_phonebook.delay')
    def test_update_phonebook(self, pb_mock):
        """
        Should call the task with the user's information.
        """
        data = {
            'city': 'Durham',
            'country': 'US',
            'WEB_DEVELOPMENT': 'y',
            'DOES_NOT_EXIST': 'y',
        }
        self.client.post(self.url, data)
        pb_mock.assert_called_with(data, self.sub.email, self.sub.token)

    @patch('news.tasks.ExactTarget')
    def test_update_phonebook_task(self, et_mock):
        """
        Should call Exact Target only with the approved information.
        """
        et = et_mock()
        data = {
            'city': 'Durham',
            'country': 'US',
            'WEB_DEVELOPMENT': 'y',
            'DOES_NOT_EXIST': 'y',
        }
        record = {
            'EMAIL_ADDRESS': self.sub.email,
            'TOKEN': self.sub.token,
            'CITY': 'Durham',
            'COUNTRY': 'US',
            'WEB_DEVELOPMENT': 'y',
        }
        self.client.post(self.url, data)
        et.data_ext().add_record.assert_called_with('PHONEBOOK',
                                                    record.keys(),
                                                    record.values())
