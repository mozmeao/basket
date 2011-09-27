
from responsys import Responsys

email = 'testchannel@example.com'

r = Responsys()
r.login('MOZILLA_API', 'firefox')

target = r.client.factory.create('InteractObject')
target.folderName = '!MasterData'
target.objectName = 'CONTACTS_LIST'

try:
    # r.merge_list_members('!MasterData', 'TEST_CONTACTS_LIST', ['EMAIL_ADDRESS_', 'EMAIL_FORMAT_'], [email, 'F'])
    u = r.retrieve_list_members(email, '!MasterData', 'CONTACTS_LIST', ['EMAIL_ADDRESS_', 'MOZILLA_AND_YOU_FLG', 'ABOUT_MOBILE_FLG', 'AURORA_FLG'])
    print u
except Exception, e:
    print e

