import json
from functools import wraps

from MySQLdb import IntegrityError
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.middleware.csrf import rotate_token
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .forms import CrearUsuarioForm, InicioSesionForm
from .passwords import generar_hash
from .database import autenticar_usuario, buscar_usuario, insertar_usuario
from .caja import listar_productos_disponibles, registrar_venta_atomica


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
        mensaje = (
            "la cuenta se encuentra bloqueada por un minuto"
            if bloqueado
            else "credenciales incorrectas"
        )
        form.add_error(None, mensaje)

    return render(request, "registration/login.html", {"form": form})


def _usuario_actual(request):
    id_usuario = request.session.get('almacen_usuario_id')
    return buscar_usuario(id_usuario=id_usuario) if id_usuario is not None else None


def es_paulina(usuario):
    return usuario is not None and usuario["username"] == "paulina"


def solo_paulina(vista):
    @wraps(vista)
    def protegida(request, *args, **kwargs):
        usuario = _usuario_actual(request)
        if usuario is None:
            return redirect("login")
        if not es_paulina(usuario):
            return render(request, "reportes/acceso_denegado.html", status=403)
        request.almacen_usuario = usuario
        return vista(request, *args, **kwargs)

    return protegida


@never_cache
def inicio(request):
    usuario = _usuario_actual(request)
    if usuario is None:
        return redirect("login")
    return render(request, "inicio.html", {"usuario": usuario, "es_paulina": es_paulina(usuario)})


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
    if not es_paulina(usuario):
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

    return render(
        request,
        "usuarios/nuevo.html",
        {"form": form, "usuario": usuario},
    )

def vista_caja(request):
    """Renderiza la pantalla de caja con el listado de productos disponibles."""
    if _usuario_actual(request) is None:
        return redirect("login")

    productos = listar_productos_disponibles()
    return render(
        request,
        "caja/pos.html",
        {"productos": productos},
    )


@require_POST
def api_confirmar_venta(request):
    """Recibe el carrito en JSON y ejecuta la transacción de venta."""
    if _usuario_actual(request) is None:
        return JsonResponse(
            {"ok": False, "error": "Debes iniciar sesión para registrar una venta."},
            status=401,
        )

    try:
        data = json.loads(request.body)
        items = data.get("items", [])
        medio_pago = data.get("medio_pago", "Efectivo")

        resultado = registrar_venta_atomica(items, medio_pago)
        return JsonResponse(
            {
                "ok": True,
                "mensaje": f"Venta #{resultado['id_venta']} registrada correctamente.",
                "id_venta": resultado["id_venta"],
                "total": resultado["total"],
            }
        )
    except ValueError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse(
            {"ok": False, "error": f"Error interno al procesar la venta: {str(e)}"},
            status=500,
        )
