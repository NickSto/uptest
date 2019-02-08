from django.conf.urls import url

from . import views

app_name = 'uptest'

urlpatterns = [
  url(r'^polo$', views.reply, name='reply'),
]
