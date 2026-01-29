import json
import logging
import re
from datetime import date

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import permission_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound, HttpResponseServerError
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import path
from django.utils.decorators import method_decorator

import sentry_sdk
import weasyprint

from basket.base.forms import EmailForm, EmailListForm
from basket.news.backends.braze import BrazeUserNotFoundByEmailError, braze
from basket.news.backends.ctms import CTMSNotFoundByEmailError, CTMSNotFoundByEmailIDError, ctms, from_vendor
from basket.news.newsletters import slug_to_vendor_id
from basket.news.utils import UNSUBSCRIBE, parse_newsletters

log = logging.getLogger(__name__)


def get_newsletter_names(contact):
    names = []
    newsletters = contact["newsletters"]
    for newsletter_slug in newsletters:
        try:
            newsletter_id = slug_to_vendor_id(newsletter_slug)
            names.append(f"{newsletter_slug} (id: {newsletter_id})")
        except KeyError:
            pass
    return names


class BasketAdminSite(admin.AdminSite):
    site_title = site_header = "Basket"

    def get_urls(self):
        admin_urls = super().get_urls()
        custom_urls = [
            path("dsar/delete/", self.admin_view(self.dsar_delete_view), name="dsar.delete"),
            path("dsar/unsubscribe/", self.admin_view(self.dsar_unsub_view), name="dsar.unsubscribe"),
            path("dsar/info/", self.admin_view(self.dsar_info_view), name="dsar.info"),
            path("dsar/info/download/", self.admin_view(self.dsar_info_download_view), name="dsar.info.download"),
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
            "title": "DSAR: Fetch User Info by Email Address",
        }
        if request.method == "POST":
            form = EmailForm(request.POST)
            if form.is_valid():
                email = form.cleaned_data["email"]
                contact, raw_contact, vendor = self._fetch_dsar_contact(email)

                context["vendor"] = vendor
                context["dsar_contact"] = contact
                context["dsar_submitted"] = True
                if contact:
                    context["dsar_contact_pretty"] = json.dumps(raw_contact, indent=2, sort_keys=True)
                    context["newsletter_names"] = get_newsletter_names(contact)

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

                def handler(emails, use_braze_backend=False):
                    # Process the emails.
                    for email in emails:
                        if use_braze_backend:
                            contact = braze.get(email=email)
                        else:
                            contact = ctms.get(email=email)
                        if contact:
                            email_id = contact["email_id"]
                            try:
                                if use_braze_backend:
                                    braze.update(
                                        contact,
                                        {
                                            "optout": True,
                                            "unsub_reason": update_data["email"]["unsubscribe_reason"],
                                            "newsletters": parse_newsletters(
                                                UNSUBSCRIBE,
                                                contact.get("newsletters", []),
                                                contact.get("newsletters", []),
                                            ),
                                        },
                                    )
                                else:
                                    ctms.interface.patch_by_email_id(email_id, update_data)
                            except CTMSNotFoundByEmailIDError:
                                # should never reach here, but best to catch it anyway
                                output.append(f"{email} not found in CTMS")
                            else:
                                output.append(f"UNSUBSCRIBED {email} ({'Braze external id:' if use_braze_backend else 'ctms id:'} {email_id}).")
                        else:
                            output.append(f"{email} not found in {'Braze' if use_braze_backend else 'CTMS'}")

                if settings.BRAZE_PARALLEL_WRITE_ENABLE:
                    try:
                        handler(emails, use_braze_backend=True)
                    except Exception as e:
                        sentry_sdk.capture_exception(e)

                    handler(emails, use_braze_backend=False)
                elif settings.BRAZE_ONLY_WRITE_ENABLE:
                    handler(emails, use_braze_backend=True)
                else:
                    handler(emails, use_braze_backend=False)

                output = "\n".join(output)

                # Reset the form
                form = EmailListForm()

        context = {
            "title": "DSAR: Unsubscribe Users by Email Address",
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

                def handler(emails, use_braze_backend=False):
                    # Process the emails.
                    for email in emails:
                        try:
                            if use_braze_backend:
                                data = braze.delete(email)
                            else:
                                data = ctms.delete(email)
                        except CTMSNotFoundByEmailError:
                            output.append(f"{email} not found in CTMS")
                        except BrazeUserNotFoundByEmailError:
                            output.append(f"{email} not found in Braze")
                        else:
                            for contact in data:
                                email_id = contact["email_id"]
                                if use_braze_backend:
                                    msg = f"DELETED {email} from Braze (external_id: {email_id})."
                                else:
                                    msg = f"DELETED {email} from CTMS (ctms id: {email_id})."
                                if contact.get("fxa_id"):
                                    msg += " fxa: YES."
                                if contact.get("mofo_contact_id"):
                                    msg += " mofo: YES."
                                output.append(msg)

                if settings.BRAZE_PARALLEL_WRITE_ENABLE:
                    try:
                        handler(emails, use_braze_backend=True)
                    except Exception as e:
                        sentry_sdk.capture_exception(e)

                    handler(emails, use_braze_backend=False)
                elif settings.BRAZE_ONLY_WRITE_ENABLE:
                    handler(emails, use_braze_backend=True)
                else:
                    handler(emails, use_braze_backend=False)

                output = "\n".join(output)

                # Reset the form
                form = EmailListForm()

        context = {
            "title": "DSAR: Delete Data by Email Address",
            "dsar_form": form,
            "dsar_output": output,
        }
        # adds default django admin context so sidebar shows etc.
        context.update(self.each_context(request))
        return render(request, "admin/dsar.html", context)

    def _fetch_dsar_contact(self, email):
        """
        Fetch contact data from CTMS or Braze based on settings.

        Returns a tuple of (contact, raw_contact, vendor) where:
        - contact: normalized contact dict (from from_vendor for CTMS, or raw dict for Braze)
        - raw_contact: raw contact data as returned by the backend
        - vendor: string indicating which backend was used ("CTMS", "Braze", or "CTMS or Braze")

        Returns (None, None, vendor) if user not found.
        Raises exceptions on backend errors.
        """
        vendor = "CTMS"
        contact = None
        raw_contact = None

        def handler(email, use_braze_backend=False, fallback_to_ctms=False):
            nonlocal contact, raw_contact, vendor
            vendor = "Braze" if use_braze_backend else "CTMS"
            try:
                if use_braze_backend:
                    contact = braze.get(email=email)
                    if not contact and fallback_to_ctms:
                        vendor = "CTMS"
                        contact = ctms.interface.get_by_alternate_id(primary_email=email)
                else:
                    contact = ctms.interface.get_by_alternate_id(primary_email=email)
            except CTMSNotFoundByEmailError:
                contact = None
            else:
                # response could be 200 with an empty list
                if contact:
                    if vendor == "Braze":
                        raw_contact = contact
                    else:
                        raw_contact = contact[0]
                        contact = from_vendor(raw_contact)
                else:
                    contact = None

            if not contact and fallback_to_ctms:
                vendor = "CTMS or Braze"

        if settings.BRAZE_READ_WITH_FALLBACK_ENABLE:
            try:
                handler(email, use_braze_backend=True, fallback_to_ctms=True)
            except Exception as e:
                sentry_sdk.capture_exception(e)
                handler(email, use_braze_backend=False)
        elif settings.BRAZE_ONLY_READ_ENABLE:
            handler(email, use_braze_backend=True)
        else:
            handler(email, use_braze_backend=False)

        return contact, raw_contact, vendor

    def _generate_dsar_pdf(self, contact, raw_contact, vendor):
        """
        Generate a PDF document containing the user's DSAR data.

        Args:
            contact: normalized contact dict
            raw_contact: raw contact data for the Raw Data section
            vendor: string indicating which backend was used

        Returns:
            bytes: PDF file content
        """
        newsletter_names = get_newsletter_names(contact)
        raw_data = json.dumps(raw_contact, indent=2, sort_keys=True)

        context = {
            "contact": contact,
            "newsletter_names": newsletter_names,
            "raw_data": raw_data,
            "vendor": vendor,
            "generated_date": date.today().isoformat(),
        }

        html = render_to_string("admin/dsar-download.html", context)

        # Block external URL fetching
        def block_url_fetcher(url, timeout=10, ssl_context=None):
            raise ValueError(f"External URL fetching is disabled: {url}")

        pdf = weasyprint.HTML(string=html, url_fetcher=block_url_fetcher).write_pdf()
        return pdf

    @method_decorator(permission_required("base.dsar_access"))
    def dsar_info_download_view(self, request):
        """Download DSAR contact info as a PDF file."""
        email = request.GET.get("email")
        if not email:
            return HttpResponseBadRequest("Missing email parameter")

        # Validate email format
        form = EmailForm({"email": email})
        if not form.is_valid():
            return HttpResponseBadRequest("Invalid email format")

        email = form.cleaned_data["email"]

        try:
            contact, raw_contact, vendor = self._fetch_dsar_contact(email)
        except Exception as e:
            sentry_sdk.capture_exception(e)
            log.error(f"DSAR PDF download error fetching contact for {email}: {e}")
            return HttpResponseServerError("Error fetching contact data")

        if not contact:
            return HttpResponseNotFound(f"User not found in {vendor}")

        try:
            pdf = self._generate_dsar_pdf(contact, raw_contact, vendor)
        except Exception as e:
            sentry_sdk.capture_exception(e)
            log.error(f"DSAR PDF generation error for {email}: {e}")
            return HttpResponseServerError("Error generating PDF")

        log.info(f"DSAR PDF download for {email} by user {request.user}")

        # Generate filename with sanitized email (only allow alphanumeric, underscore, hyphen)
        safe_email = re.sub(r"[^a-zA-Z0-9_-]", "_", email)
        filename = f"data-basket-{safe_email}-{date.today().isoformat()}.pdf"

        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Content-Length"] = len(pdf)
        return response
