from django import forms


class ImageUploadWidget(forms.ClearableFileInput):
    template_name = "core/widgets/image_upload.html"

    def __init__(self, attrs=None):
        attrs = {} if attrs is None else dict(attrs)
        attrs.setdefault("accept", "image/*")
        super().__init__(attrs)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        widget = context["widget"]
        url = ""
        if value:
            try:
                url = value.url
            except (ValueError, AttributeError):
                url = ""
        widget["preview_url"] = url
        css = widget["attrs"].get("class", "")
        widget["attrs"]["class"] = f"{css} image-upload__input".strip()
        return context
