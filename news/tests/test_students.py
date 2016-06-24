from django.test import TestCase

from mock import patch

from news.tasks import update_student_ambassadors, RetryTask
from news.utils import generate_token


class UpdateStudentAmbassadorsTest(TestCase):
    def setUp(self):
        self.token = generate_token()
        self.url = '/news/custom_update_student_ambassadors/%s/' % \
                   self.token
        self.data = {
            'FIRST_NAME': 'Testy',
            'LAST_NAME': 'McTestface',
            'EMAIL_ADDRESS': 'tmctestface@example.com',
            'STUDENTS_CURRENT_STATUS': 'student',
            'STUDENTS_SCHOOL': 'Testington U',
            'STUDENTS_GRAD_YEAR': '2014',
            'STUDENTS_MAJOR': 'computer engineering',
            'COUNTRY_': 'GR',
            'STUDENTS_CITY': 'Testington',
            'STUDENTS_ALLOW_SHARE': 'N',
        }
        self.submitted_data = {
            'first_name': 'Testy',
            'last_name': 'McTestface',
            'email': 'tmctestface@example.com',
            'fsa_current_status': 'student',
            'fsa_school': 'Testington U',
            'fsa_grad_year': '2014',
            'fsa_major': 'computer engineering',
            'country': 'GR',
            'fsa_city': 'Testington',
            'fsa_allow_share': False,
        }

    @patch('news.views.update_student_ambassadors.delay')
    def test_update_student_ambassadors(self, usa_mock):
        """
        Should call the task with the user's information.
        """
        self.client.post(self.url, self.data)
        usa_mock.assert_called_with(self.data, self.token)

    @patch('news.tasks.get_user_data')
    @patch('news.tasks.sfdc')
    def test_update_student_ambassadors_task(self, sfdc_mock, gud_mock):
        """
        Should call Exact Target only with the approved information.
        """
        user_data = {'token': self.token}
        gud_mock.return_value = user_data
        self.client.post(self.url, self.data)
        sfdc_mock.update.assert_called_with(user_data, self.submitted_data)

    @patch('news.tasks.get_user_data')
    @patch('news.tasks.sfdc')
    def test_update_student_ambassadors_task_retry(self, sfdc_mock, gud_mock):
        """
        Should retry if no user data
        """
        gud_mock.return_value = None
        with self.assertRaises(RetryTask):
            update_student_ambassadors(self.data, self.token)

        sfdc_mock.assert_not_called()
