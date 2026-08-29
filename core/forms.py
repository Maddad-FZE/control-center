from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

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


class AppearanceForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ("theme",)
        widgets = {"theme": forms.Select()}


class SiteSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = (
            "title",
            "tagline",
            "logo",
            "favicon",
            "weather_location",
            "crt_enabled",
            "services_host",
        )
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Home Server Command Center"}),
            "tagline": forms.TextInput(attrs={"placeholder": "Short line under the title"}),
            "weather_location": forms.TextInput(
                attrs={"placeholder": "City name, e.g. Dubai"}
            ),
            "services_host": forms.TextInput(
                attrs={"placeholder": "e.g. 192.168.0.40"}
            ),
            "crt_enabled": forms.CheckboxInput(),
        }


class SetupAdminForm(forms.Form):
    username = forms.CharField(max_length=150)
    password1 = forms.CharField(widget=forms.PasswordInput)
    password2 = forms.CharField(widget=forms.PasswordInput)

    def clean_password1(self):
        password = self.cleaned_data.get("password1", "")
        validate_password(password)
        return password

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Passwords do not match.")
        return cleaned
