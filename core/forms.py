from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import SiteSettings
from .widgets import ImageUploadWidget


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("email", "first_name", "last_name")
        widgets = {
            "email": forms.EmailInput(attrs={"placeholder": "email@example.com"}),
            "first_name": forms.TextInput(attrs={"placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Last name"}),
        }


class SiteThemeForm(forms.Form):
    theme = forms.ChoiceField(required=True, choices=(), label="Theme")

    def __init__(self, *args, site_theme="wood", **kwargs):
        super().__init__(*args, **kwargs)
        from core.themes.registry import get_packs

        packs = list(get_packs().values())
        self.packs = packs
        self.fields["theme"].choices = [(pack.slug, pack.name) for pack in packs] or [
            ("wood", "Wood & Orange")
        ]
        self.fields["theme"].initial = site_theme

    def clean_theme(self):
        from core.themes.registry import get_theme

        slug = (self.cleaned_data.get("theme") or "").strip()
        if get_theme(slug) is None:
            raise ValidationError("Choose a theme that is installed.")
        return slug


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
            "require_2fa_for_admins",
            "require_2fa_for_all",
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
            "logo": ImageUploadWidget(),
            "favicon": ImageUploadWidget(attrs={"accept": "image/*,.ico,image/x-icon"}),
            "crt_enabled": forms.CheckboxInput(),
            "wizard_enabled": forms.CheckboxInput(attrs={"data-wizard-master": "1"}),
            "wizard_notify": forms.CheckboxInput(attrs={"data-wizard-notify": "1"}),
            "require_2fa_for_admins": forms.CheckboxInput(),
            "require_2fa_for_all": forms.CheckboxInput(),
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("wizard_enabled") and self.instance.pk:
            cleaned["wizard_notify"] = self.instance.wizard_notify
        if not cleaned.get("kuma_password") and self.instance.pk:
            cleaned["kuma_password"] = self.instance.kuma_password
        return cleaned


class SetupAdminForm(forms.Form):
    username = forms.CharField(max_length=150, label="Admin username")
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)
    title = forms.CharField(
        max_length=120,
        label="Name",
        widget=forms.TextInput(attrs={"placeholder": "My Control Center"}),
    )
    tagline = forms.CharField(
        max_length=200,
        required=False,
        label="Tagline",
        widget=forms.TextInput(attrs={"placeholder": "A short line under the name"}),
    )
    weather_location = forms.CharField(
        max_length=120,
        required=False,
        label="Weather city",
        widget=forms.TextInput(attrs={"placeholder": "e.g. Dubai"}),
    )
    logo = forms.ImageField(required=False, widget=ImageUploadWidget())
    favicon = forms.FileField(
        required=False,
        widget=ImageUploadWidget(attrs={"accept": "image/*,.ico,image/x-icon"}),
    )
    wizard_enabled = forms.BooleanField(
        required=False,
        initial=True,
        label="Enable Merlin for tutorials and help",
        widget=forms.CheckboxInput(),
    )
    theme = forms.ChoiceField(
        required=False,
        choices=(),
        label="Theme",
        widget=forms.Select(),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.themes.registry import get_packs

        packs = get_packs()
        choices = [(pack.slug, pack.name) for pack in packs.values()] or [
            ("wood", "Wood & Orange")
        ]
        self.fields["theme"].choices = choices
        self.fields["theme"].initial = "wood" if "wood" in packs or not packs else choices[0][0]

    def clean_theme(self):
        from core.themes.registry import get_theme

        slug = (self.cleaned_data.get("theme") or "wood").strip()
        if get_theme(slug) is None:
            return "wood"
        return slug

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
