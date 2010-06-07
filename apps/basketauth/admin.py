from django.contrib import admin


class ConsumerAdmin(admin.ModelAdmin):
    fields = ('name', 'key', 'secret')
    readonly_fields = ('key', 'secret')

    def save_model(self, request, obj, form, change):
        if change is False:
            obj.generate_random_codes()
        else:
            obj.save()
