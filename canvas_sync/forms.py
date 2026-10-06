from django import forms

from .models import CanvasConnection


class CanvasConnectionForm(forms.ModelForm):
    access_token = forms.CharField(
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Leave blank to keep your current token.",
    )

    class Meta:
        model = CanvasConnection
        fields = ("canvas_base_url", "access_token")

    def clean_canvas_base_url(self):
        url = self.cleaned_data["canvas_base_url"]
        return url.rstrip("/")

    def clean_access_token(self):
        token = self.cleaned_data.get("access_token")

        if token:
            return token

        if self.instance and self.instance.pk:
            return self.instance.access_token

        raise forms.ValidationError("Canvas access token is required.")