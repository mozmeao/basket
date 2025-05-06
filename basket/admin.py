import json

from django.contrib import admin
from django.contrib.auth.decorators import permission_required
from django.shortcuts import render
from django.urls import path
from django.utils.decorators import method_decorator

from basket.base.forms import EmailForm, EmailListForm
from basket.news.backends.ctms import (
    CTMSNotFoundByEmailError,
    CTMSNotFoundByEmailIDError,
    ctms,
)
from basket.news.newsletters import newsletter_obj


def get_newsletter_names(ctms_contact):
    names = []
    newsletters = ctms_contact["newsletters"]
    for nl in newsletters:
        if not nl["subscribed"]:
            continue

        nl_slug = nl["name"]
        nl_obj = newsletter_obj(nl_slug)
        if nl_obj:
            nl_name = nl_obj.title
        else:
            nl_name = ""
        names.append(f"{nl_name} (id: {nl_slug})")

    return names


class BasketAdminSite(admin.AdminSite):
    site_title = site_header = "Basket"

    def get_urls(self):
        admin_urls = super().get_urls()
        custom_urls = [
            path("dsar/delete/", self.admin_view(self.dsar_delete_view), name="dsar.delete"),
            path("dsar/unsubscribe/", self.admin_view(self.dsar_unsub_view), name="dsar.unsubscribe"),
            path("dsar/info/", self.admin_view(self.dsar_info_view), name="dsar.info"),
        ]
        # very important that custom_urls are first
        return custom_urls + admin_urls

    def get_app_list(self, request, app_label=None):
        # checks if the user has permission to see DSAR in the list
        app_list = super().get_app_list(request, app_label=app_label)
        has_perms = request.user.has_perm("base.dsar_access")
        if not has_perms:
            return app_list

        model_perms = (
            {
                "add": True,
                "change": True,
                "delete": True,
                "view": True,
            },
        )
        app_list += [
            {
                "name": "DSAR Admin",
                "app_label": "DSAR Admin",
                "has_module_perms": True,
                "models": [
                    {
                        "name": "DSAR Delete",
                        "object_name": "dsardelete",
                        "admin_url": "/admin/dsar/delete/",
                        "view_only": True,
                        "perms": model_perms,
                    },
                    {
                        "name": "DSAR Unsubscribe",
                        "object_name": "dsarunsubscribe",
                        "admin_url": "/admin/dsar/unsubscribe/",
                        "view_only": True,
                        "perms": model_perms,
                    },
                    {
                        "name": "DSAR Get Info",
                        "object_name": "dsargetingo",
                        "admin_url": "/admin/dsar/info/",
                        "view_only": True,
                        "perms": model_perms,
                    },
                ],
            }
        ]
        return app_list

    @method_decorator(permission_required("base.dsar_access"))
    def dsar_info_view(self, request):
        form = EmailForm()
        context = {
            "title": "DSAR: Fetch CTMS User Info by Email Address",
        }
        if request.method == "POST":
            form = EmailForm(request.POST)
            if form.is_valid():
                email = form.cleaned_data["email"]
                try:
                    contact = ctms.interface.get_by_alternate_id(primary_email=email)
                except CTMSNotFoundByEmailError:
                    contact = None
                else:
                    # response could be 200 with an empty list
                    if contact:
                        contact = contact[0]
                        context["dsar_contact_pretty"] = json.dumps(contact, indent=2, sort_keys=True)
                        context["newsletter_names"] = get_newsletter_names(contact)
                    else:
                        contact = None

                context["dsar_contact"] = contact
                context["dsar_submitted"] = True

        context["dsar_form"] = form
        # adds default django admin context so sidebar shows etc.
        context.update(self.each_context(request))
        return render(request, "admin/dsar-info.html", context)

    @method_decorator(permission_required("base.dsar_access"))
    def dsar_unsub_view(self, request):
        form = EmailListForm()
        output = None

        if request.method == "POST":
            form = EmailListForm(request.POST)
            if form.is_valid():
                emails = form.cleaned_data["emails"]
                output = []
                # sets global optout and removes all newsletter
                # and waitlist subscriptions
                update_data = {
                    "email": {
                        "has_opted_out_of_email": True,
                        "unsubscribe_reason": "User requested global unsubscribe",
                    },
                    "newsletters": "UNSUBSCRIBE",
                    "waitlists": "UNSUBSCRIBE",
                }

                # Process the emails.
                for email in emails:
                    contact = ctms.get(email=email)
                    if contact:
                        email_id = contact["email_id"]
                        try:
                            ctms.interface.patch_by_email_id(email_id, update_data)
                        except CTMSNotFoundByEmailIDError:
                            # should never reach here, but best to catch it anyway
                            output.append(f"{email} not found in CTMS")
                        else:
                            output.append(f"UNSUBSCRIBED {email} (ctms id: {email_id}).")
                    else:
                        output.append(f"{email} not found in CTMS")

                output = "\n".join(output)

                # Reset the form
                form = EmailListForm()

        context = {
            "title": "DSAR: Unsubscribe CTMS Users by Email Address",
            "dsar_form": form,
            "dsar_output": output,
        }
        # adds default django admin context so sidebar shows etc.
        context.update(self.each_context(request))
        return render(request, "admin/dsar.html", context)

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
