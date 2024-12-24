from django.contrib.admin.apps import AdminConfig


class BasketAdminConfig(AdminConfig):
    default_site = "basket.admin.BasketAdminSite"
