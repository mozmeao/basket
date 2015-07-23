from django.test import TestCase

from mock import patch

from news.utils import generate_token


class UpdatePhonebookTest(TestCase):
    def setUp(self):
        self.token = generate_token()
        self.url = '/news/custom_update_phonebook/%s/' % self.token

    @patch('news.views.update_phonebook')
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
        pb_mock.delay.assert_called_with(data, self.token)

    @patch('news.tasks.ExactTarget')
    @patch('news.tasks.get_user_data')
    def test_update_phonebook_task(self, user_data_mock, et_mock):
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
            'EMAIL_ADDRESS': 'dude@example.com',
            'TOKEN': self.token,
            'CITY': 'Durham',
            'COUNTRY': 'US',
            'WEB_DEVELOPMENT': 'y',
        }
        user_data_mock.return_value = {'email': 'dude@example.com'}
        self.client.post(self.url, data)
        et.data_ext().add_record.assert_called_with('PHONEBOOK',
                                                    record.keys(),
                                                    record.values())
