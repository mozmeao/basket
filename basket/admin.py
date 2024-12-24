from django.contrib import admin


class BasketAdminSite(admin.AdminSite):
    site_title = site_header = "Basket"
    index_template = "admin/basket_index.html"
