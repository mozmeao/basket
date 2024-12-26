from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import permission_required
from django.shortcuts import render

from basket.base.forms import EmailListForm
from basket.news.backends.ctms import (
    CTMSNotFoundByEmailError,
    ctms,
)


@staff_member_required
@permission_required("base.dsar_access")
def admin_dsar(request):
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
        "title": "Data Subject Access Request",
        "form": form,
        "output": output,
    }

    return render(request, "admin/dsar.html", context)
