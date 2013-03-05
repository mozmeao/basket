from django.contrib import admin
from django.contrib.admin.sites import NotRegistered

from piston.models import Consumer


class ConsumerAdmin(admin.ModelAdmin):
    fields = ('name', 'key', 'secret', 'status')
    readonly_fields = ('key', 'secret')

    def save_model(self, request, obj, form, change):
        obj.status = 'accepted'
        if change is False:
            obj.generate_random_codes()
        else:
            obj.save()


try:
    admin.site.unregister(Consumer)
except NotRegistered:
    pass

admin.site.register(Consumer, ConsumerAdmin)
