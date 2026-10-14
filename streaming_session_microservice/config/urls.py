"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from streaming_sessions.views import (
    health_check,
    session_list,
    session_detail,
    register,
    user_login,
)

urlpatterns = [
    path("health/", health_check),
    path('admin/', admin.site.urls),
    path("api/register/", register),
    path("api/login/", user_login),
    
    path("api/sessions/", session_list),
    path("api/sessions/<int:pk>/", session_detail),
]
