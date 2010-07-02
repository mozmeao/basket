ALTER TABLE emailer_email ADD COLUMN from_name varchar(255) NOT NULL;
ALTER TABLE emailer_email ADD COLUMN from_email varchar(75) NOT NULL;
ALTER TABLE emailer_email ADD COLUMN reply_to_email varchar(75) NOT NULL;
UPDATE emailer_email SET from_name = 'Firefox Home Account Setup' WHERE name = 'iphone-reg';
UPDATE emailer_email SET from_name = 'Firefox Home Account Setup' WHERE name = 'iphone-reminder';
UPDATE emailer_email SET from_email = 'firefox-home-support@mozilla.com' WHERE name = 'iphone-reg';
UPDATE emailer_email SET from_email = 'firefox-home-support@mozilla.com' WHERE name = 'iphone-reminder';
UPDATE emailer_email SET reply_to_email = 'firefox-home-support@mozilla.com' WHERE name = 'iphone-reg';
UPDATE emailer_email SET reply_to_email = 'firefox-home-support@mozilla.com' WHERE name = 'iphone-reminder';
