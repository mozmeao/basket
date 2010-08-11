ALTER TABLE emailer_recipient MODIFY email_id VARCHAR(255) NOT NULL;
UPDATE emailer_recipient er SET er.email_id = 'firefox-home-instructions-initial' WHERE (SELECT ee.name FROM emailer_email ee WHERE ee.id = er.email_id) = 'iphone-reg';
UPDATE emailer_recipient er SET er.email_id = 'firefox-home-instructions-reminder' WHERE (SELECT ee.name FROM emailer_email ee WHERE ee.id = er.email_id) = 'iphone-reminder';
DROP TABLE emailer_email;
