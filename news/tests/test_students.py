from django.test import TestCase

from mock import patch

from news import models


class UpdateStudentAmbassadorsTest(TestCase):
    def setUp(self):
        self.sub = models.Subscriber.objects.create(email='dude@example.com')
        self.url = '/news/custom_update_student_ambassadors/%s/' % \
                   self.sub.token
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
        pb_mock.assert_called_with(self.data, self.sub.email, self.sub.token)

    @patch('news.tasks.ExactTarget')
    def test_update_phonebook_task(self, et_mock):
        """
        Should call Exact Target only with the approved information.
        """
        et = et_mock()
        record = self.data.copy()
        record.update({'EMAIL_ADDRESS': self.sub.email,
                       'TOKEN': self.sub.token})
        self.client.post(self.url, self.data)
        et.data_ext().add_record.assert_called_with('Student_Ambassadors',
                                                    record.keys(),
                                                    record.values())
