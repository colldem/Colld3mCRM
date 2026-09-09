from django.urls import path

from . import api

app_name = "api"
urlpatterns = [
    path("me", api.me, name="me"),
    path("contacts", api.contacts_collection, name="contacts"),
    path("contacts/<int:pk>", api.contact_item, name="contact"),
    path("companies", api.companies_collection, name="companies"),
    path("companies/<int:pk>", api.company_item, name="company"),
    path("activities", api.activities_collection, name="activities"),
    path("reminders", api.reminders_collection, name="reminders"),
]
