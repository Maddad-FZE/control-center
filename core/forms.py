from django import forms
from django.contrib.auth.models import User

from .models import SiteSettings, UserProfile


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("email", "first_name", "last_name")
        widgets = {
            "email": forms.EmailInput(attrs={"placeholder": "email@example.com"}),
            "first_name": forms.TextInput(attrs={"placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Last name"}),
        }


class SettingsForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ("theme", "crt_enabled")
        widgets = {
            "theme": forms.Select(),
            "crt_enabled": forms.CheckboxInput(),
        }


class SiteSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = ("logo", "favicon", "weather_location")
        widgets = {
            "weather_location": forms.TextInput(
                attrs={"placeholder": "City name, e.g. Dubai"}
            ),
        }
