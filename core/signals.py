from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed

from .models import UserProfile, log_audit


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    log_audit("login", request=request, user=user, message=f"{user.username} signed in")


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user:
        log_audit("logout", request=request, user=user, message=f"{user.username} signed out")


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request, **kwargs):
    username = credentials.get("username", "")
    log_audit(
        "login_failed",
        request=request,
        message=f"Failed login for {username}",
        username=username,
    )
