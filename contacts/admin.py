from django.contrib import admin

from .models import Activity, Category, Company, EmailAddress, Person, PersonCompanyLink, PhoneNumber, PostalAddress, Reminder, Tag, WebLink


for model in [Person, Company, PersonCompanyLink, PhoneNumber, EmailAddress, PostalAddress, WebLink, Tag, Category, Activity, Reminder]:
    admin.site.register(model)
