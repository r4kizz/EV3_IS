from MySQLdb import IntegrityError
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.middleware.csrf import rotate_token
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .forms import CrearUsuarioForm, InicioSesionForm
from .passwords import generar_hash
from .database import autenticar_usuario, buscar_usuario, insertar_usuario


@never_cache
@require_http_methods(["GET", "POST"])
def iniciar_sesion(request):
    form = InicioSesionForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        id_usuario, bloqueado = autenticar_usuario(form.cleaned_data["username"], form.cleaned_data["password"])
        if id_usuario is not None:
            request.session.flush()
            request.session["almacen_usuario_id"] = id_usuario
            rotate_token(request)
            return redirect("inicio")
        mensaje = "la cuenta se encuentra bloqueada" if bloqueado else "credenciales incorrectas"
        form.add_error(None, mensaje)

    return render(request, "registration/login.html", {"form": form})


def _usuario_actual(request):
    id_usuario = request.session.get('almacen_usuario_id')
    return buscar_usuario(id_usuario=id_usuario) if id_usuario is not None else None


@never_cache
def inicio(request):
    usuario = _usuario_actual(request)
    if usuario is None:
        return redirect("login")
    return render(request, "inicio.html", {"usuario": usuario, "puede_crear_usuarios": usuario["username"] == "paulina"})


@require_POST
def cerrar_sesion(request):
    request.session.flush()
    rotate_token(request)
    return redirect("login")


@never_cache
@require_http_methods(["GET", "POST"])
def nuevo_usuario(request):
    usuario = _usuario_actual(request)
    if usuario is None:
        return redirect("login")
    if usuario["username"] != "paulina":
        return HttpResponseForbidden("Solo Paulina puede crear usuarios.")

    form = CrearUsuarioForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        datos = form.cleaned_data
        try:
            insertar_usuario(datos["username"], datos["correo"], generar_hash(datos["password"]))
        except IntegrityError as error:
            if error.args[0] != 1062:
                raise
            form.add_error(None, "El nombre de usuario o el correo ya está registrado.")
        else:
            messages.success(request, "Usuario creado correctamente.")
            return redirect("nuevo_usuario")

    return render(request, "usuarios/nuevo.html", {"form": form})
