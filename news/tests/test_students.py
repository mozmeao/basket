from django.test import TestCase

from mock import patch

from news.utils import generate_token


class UpdateStudentAmbassadorsTest(TestCase):
    def setUp(self):
        self.token = generate_token()
        self.url = '/news/custom_update_student_ambassadors/%s/' % \
                   self.token
        self.data = {'FIRST_NAME': 'Foo',
                     'LAST_NAME': 'Bar',
                     'STUDENTS_CURRENT_STATUS': 'student',
                     'STUDENTS_SCHOOL': 'tuc',
                     'STUDENTS_GRAD_YEAR': '2014',
                     'STUDENTS_MAJOR': 'computer engineering',
                     'COUNTRY': 'GR',
                     'STUDENTS_CITY': 'Athens',
                     'STUDENTS_ALLOW_SHARE': 'N'}

    @patch('news.views.update_student_ambassadors.delay')
    def test_update_phonebook(self, pb_mock):
        """
        Should call the task with the user's information.
        """
        self.client.post(self.url, self.data)
        pb_mock.assert_called_with(self.data, self.token)

    @patch('news.tasks.ExactTarget')
    @patch('news.tasks.get_user_data')
    def test_update_phonebook_task(self, user_data_mock, et_mock):
        """
        Should call Exact Target only with the approved information.
        """
        et = et_mock()
        record = self.data.copy()
        record.update({'EMAIL_ADDRESS': 'dude@example.com',
                       'TOKEN': self.token})
        user_data_mock.return_value = {'email': 'dude@example.com'}
        self.client.post(self.url, self.data)
        et.data_ext().add_record.assert_called_with('Student_Ambassadors',
                                                    record.keys(),
                                                    record.values())
