from django import forms

from .passwords import cumple_politica


class InicioSesionForm(forms.Form):
    username = forms.CharField(label="Usuario", max_length=100)
    password = forms.CharField(
        label="Contraseña", strip=False, max_length=4096,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class CrearUsuarioForm(forms.Form):
    username = forms.CharField(label="Usuario", max_length=100)
    correo = forms.EmailField(label="Correo", max_length=150)
    password = forms.CharField(
        label="Contraseña", strip=False, max_length=4096,
        help_text="Mínimo 8 caracteres, con un número, una mayúscula, una minúscula y un símbolo.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirmacion = forms.CharField(
        label="Confirma la contraseña", strip=False, max_length=4096,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not cumple_politica(password):
            raise forms.ValidationError("La contraseña no cumple los requisitos indicados.")
        return password

    def clean(self):
        datos = super().clean()
        if "password" in datos and "confirmacion" in datos and datos["password"] != datos["confirmacion"]:
            self.add_error("confirmacion", "Las contraseñas no coinciden.")
        return datos
