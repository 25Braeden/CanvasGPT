from django import forms
from django.views.decorators.debug import sensitive_variables

from .models import CanvasConnection
from .services import CanvasSyncError, _url_origin


class CanvasConnectionForm(forms.ModelForm):
    canvas_base_url = forms.URLField(
        widget=forms.URLInput(
            attrs={
                "autocomplete": "off",
                "placeholder": "https://your-school.instructure.com",
            }
        )
    )
    access_token = forms.CharField(
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"autocomplete": "new-password"},
        ),
        required=False,
        help_text="Leave blank to keep your current token.",
    )

    class Meta:
        model = CanvasConnection
        fields = ("canvas_base_url", "access_token")

    def clean_canvas_base_url(self):
        url = self.cleaned_data["canvas_base_url"]
        try:
            _url_origin(url)
        except (CanvasSyncError, ValueError):
            raise forms.ValidationError("Enter a valid HTTPS Canvas URL.") from None
        return url.rstrip("/")

    @sensitive_variables("token", "self")
    def clean_access_token(self):
        token = self.cleaned_data.get("access_token")

        if token:
            return token

        if self.instance.pk and self.instance.access_token_ciphertext:
            new_url = self.cleaned_data.get("canvas_base_url")
            if new_url and new_url != self.instance.canvas_base_url:
                try:
                    same_origin = _url_origin(new_url) == _url_origin(self.instance.canvas_base_url)
                except (CanvasSyncError, ValueError):
                    same_origin = False
                if not same_origin:
                    raise forms.ValidationError("Enter a token for the new Canvas address.")
            return ""

        raise forms.ValidationError("Canvas access token is required.")