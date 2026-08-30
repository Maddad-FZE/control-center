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
    kuma_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            render_value=True,
            attrs={"autocomplete": "new-password"},
        ),
    )

    class Meta:
        model = SiteSettings
        fields = (
            "title",
            "tagline",
            "logo",
            "favicon",
            "weather_location",
            "crt_enabled",
            "wizard_enabled",
            "wizard_notify",
            "services_host",
            "kuma_username",
            "kuma_password",
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
            "kuma_username": forms.TextInput(attrs={"placeholder": "cc-monitor"}),
            "crt_enabled": forms.CheckboxInput(),
            "wizard_enabled": forms.CheckboxInput(attrs={"data-wizard-master": "1"}),
            "wizard_notify": forms.CheckboxInput(attrs={"data-wizard-notify": "1"}),
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("wizard_enabled") and self.instance.pk:
            cleaned["wizard_notify"] = self.instance.wizard_notify
        if not cleaned.get("kuma_password") and self.instance.pk:
            cleaned["kuma_password"] = self.instance.kuma_password
        return cleaned


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
