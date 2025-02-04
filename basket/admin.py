from django.contrib import admin
from django.contrib.auth.decorators import permission_required
from django.shortcuts import render
from django.urls import path
from django.utils.decorators import method_decorator

from basket.base.forms import EmailListForm
from basket.news.backends.ctms import (
    CTMSNotFoundByEmailError,
    ctms,
)


class BasketAdminSite(admin.AdminSite):
    site_title = site_header = "Basket"

    def get_urls(self):
        admin_urls = super().get_urls()
        custom_urls = [
            path("dsar/delete/", self.admin_view(self.dsar_delete_view), name="dsar.delete"),
        ]
        # very important that custom_urls are first
        return custom_urls + admin_urls

    def get_app_list(self, request, app_label=None):
        # checks if the user has permission to see DSAR in the list
        has_perms = request.user.has_perm("base.dsar_access")
        app_list = super().get_app_list(request, app_label=app_label)
        app_list += [
            {
                "name": "DSAR Admin",
                "app_label": "DSAR Admin",
                "has_module_perms": has_perms,
                "models": [
                    {
                        "name": "DSAR Delete",
                        "object_name": "dsardelete",
                        "admin_url": "/admin/dsar/delete/",
                        "view_only": True,
                        "perms": {
                            "add": has_perms,
                            "change": has_perms,
                            "delete": has_perms,
                            "view": has_perms,
                        },
                    }
                ],
            }
        ]
        return app_list

    @method_decorator(permission_required("base.dsar_access"))
    def dsar_delete_view(self, request):
        form = EmailListForm()
        output = None

        if request.method == "POST":
            form = EmailListForm(request.POST)
            if form.is_valid():
                emails = form.cleaned_data["emails"]
                output = []

                # Process the emails.
                for email in emails:
                    try:
                        data = ctms.delete(email)
                    except CTMSNotFoundByEmailError:
                        output.append(f"{email} not found in CTMS")
                    else:
                        for contact in data:
                            email_id = contact["email_id"]
                            msg = f"DELETED {email} (ctms id: {email_id})."
                            if contact["fxa_id"]:
                                msg += " fxa: YES."
                            if contact["mofo_contact_id"]:
                                msg += " mofo: YES."
                            output.append(msg)

                output = "\n".join(output)

                # Reset the form
                form = EmailListForm()

        context = {
            "title": "DSAR: Delete CTMS Data by Email Address",
            "dsar_form": form,
            "dsar_output": output,
        }
        # adds default django admin context so sidebar shows etc.
        context.update(self.each_context(request))
        return render(request, "admin/dsar.html", context)
