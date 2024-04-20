from django.urls import re_path

from . import views

app_name = 'uptest'

urlpatterns = [
  re_path(r'^polo$', views.reply, name='reply'),
]
