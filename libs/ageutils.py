from datetime import datetime, timedelta

ten_days = timedelta(10)

def subscription_older_than_ten_days(subscription):
    return (datetime.today() - subscription.created) > ten_days
