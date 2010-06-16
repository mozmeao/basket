ALTER TABLE emailer_email ADD COLUMN mailchimp_campaign varchar(20) NOT NULL;
ALTER TABLE emailer_email ADD COLUMN mailchimp_list varchar(20) NOT NULL;
UPDATE emailer_email SET emailer_class = 'emailer.base.MailChimpEmailer' WHERE name = 'iphone-reg';
UPDATE emailer_email SET mailchimp_list = '52f11438bb' WHERE name = 'iphone-reg';
UPDATE emailer_email SET mailchimp_list = 'aa3479dc85' WHERE name = 'iphone-reminder';
