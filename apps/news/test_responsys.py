
from responsys import Responsys

email = 'test-f@example.com'

r = Responsys()
r.login('MOZILLA_API', 'firefox')

target = r.client.factory.create('InteractObject')
target.folderName = '!MasterData'
target.objectName = 'TEST_CONTACTS_LIST'

try:
    # r.merge_list_members('!MasterData', 'TEST_CONTACTS_LIST', ['EMAIL_ADDRESS_', 'EMAIL_FORMAT_'], [email, 'F'])
    u = r.retrieve_list_members(email, '!MasterData', 'TEST_CONTACTS_LIST', ['EMAIL_ADDRE_', 'EMAIL_FORMAT_'])
    print u
except Exception, e:
    print str(e.fault.detail)

