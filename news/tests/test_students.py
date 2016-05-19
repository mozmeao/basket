from django.test import TestCase

from mock import patch

from news.utils import generate_token


class UpdateStudentAmbassadorsTest(TestCase):
    def setUp(self):
        self.token = generate_token()
        self.url = '/news/custom_update_student_ambassadors/%s/' % \
                   self.token
        self.data = {'FIRST_NAME': 'Testy',
                     'LAST_NAME': 'McTestface',
                     'EMAIL_ADDRESS': 'tmctestface@example.com',
                     'STUDENTS_CURRENT_STATUS': 'student',
                     'STUDENTS_SCHOOL': 'Testington U',
                     'STUDENTS_GRAD_YEAR': '2014',
                     'STUDENTS_MAJOR': 'computer engineering',
                     'COUNTRY': 'GR',
                     'STUDENTS_CITY': 'Testington',
                     'STUDENTS_ALLOW_SHARE': 'N'}

    @patch('news.views.update_student_ambassadors.delay')
    def test_update_student_ambassadors(self, usa_mock):
        """
        Should call the task with the user's information.
        """
        self.client.post(self.url, self.data)
        usa_mock.assert_called_with(self.data, self.token)

    @patch('news.tasks.sfmc')
    def test_update_student_ambassadors_task(self, sfmc_mock):
        """
        Should call Exact Target only with the approved information.
        """
        record = self.data.copy()
        record['TOKEN'] = self.token
        self.client.post(self.url, self.data)
        sfmc_mock.update_row.assert_called_with('Student_Ambassadors', record)
