from contextlib import closing

import MySQLdb
from MySQLdb.cursors import DictCursor
from django import forms
from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from .views import solo_paulina


class ProveedorForm(forms.Form):
    rut = forms.CharField(
        label="RUT",
        max_length=20,
        widget=forms.TextInput(attrs={"placeholder": "Ej: 76.123.456-7", "class": "form-control"}),
    )
    nombre = forms.CharField(
        label="Nombre o Razón Social",
        max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "Ej: Distribuidora Central Ltda.", "class": "form-control"}),
    )
    telefono = forms.CharField(
        label="Teléfono",
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Ej: +56 9 1234 5678", "class": "form-control"}),
    )


@never_cache
@solo_paulina
@require_http_methods(["GET", "POST"])
def proveedores(request, id_proveedor=None):
    usuario = request.almacen_usuario

    editando = id_proveedor is not None
    error_rut = None

    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor(DictCursor) as cursor:
            proveedor = None

            if editando:
                cursor.execute(
                    """
                    SELECT id_proveedor, rut, nombre, telefono
                    FROM proveedor
                    WHERE id_proveedor = %s
                    """,
                    (id_proveedor,),
                )
                proveedor = cursor.fetchone()
                if proveedor is None:
                    raise Http404("Proveedor no encontrado.")

            form = ProveedorForm(
                request.POST if request.method == "POST" else None,
                initial=proveedor,
            )

            if request.method == "POST" and form.is_valid():
                datos = form.cleaned_data
                try:
                    if editando:
                        cursor.execute(
                            """
                            UPDATE proveedor
                            SET rut = %s, nombre = %s, telefono = %s
                            WHERE id_proveedor = %s
                            """,
                            (datos["rut"].strip(), datos["nombre"].strip(), datos["telefono"].strip(), id_proveedor),
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO proveedor (rut, nombre, telefono, id_usuario)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (datos["rut"].strip(), datos["nombre"].strip(), datos["telefono"].strip(), usuario["id_usuario"]),
                        )
                    conexion.commit()
                    return redirect("proveedores")
                except MySQLdb.IntegrityError as error:
                    conexion.rollback()
                    if error.args[0] == 1062:
                        error_rut = "El RUT ingresado ya se encuentra registrado para otro proveedor."
                        form.add_error("rut", error_rut)
                    else:
                        raise

            # Listado y búsqueda de proveedores
            busqueda = request.GET.get("q", "").strip()
            if busqueda:
                termino = f"%{busqueda}%"
                cursor.execute(
                    """
                    SELECT p.id_proveedor, p.rut, p.nombre, p.telefono, u.username AS registrado_por
                    FROM proveedor p
                    LEFT JOIN usuario u ON p.id_usuario = u.id_usuario
                    WHERE p.nombre LIKE %s OR p.rut LIKE %s
                    ORDER BY p.nombre ASC
                    """,
                    (termino, termino),
                )
            else:
                cursor.execute(
                    """
                    SELECT p.id_proveedor, p.rut, p.nombre, p.telefono, u.username AS registrado_por
                    FROM proveedor p
                    LEFT JOIN usuario u ON p.id_usuario = u.id_usuario
                    ORDER BY p.nombre ASC
                    """
                )
            listado = cursor.fetchall()

    return render(
        request,
        "proveedores/proveedores.html",
        {
            "form": form,
            "proveedores": listado,
            "proveedor_editado": proveedor,
            "busqueda": busqueda,
            "error_rut": error_rut,
        },
    )


@never_cache
@solo_paulina
@require_POST
def eliminar_proveedor(request, id_proveedor):
    error_eliminar = None
    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor(DictCursor) as cursor:
            try:
                cursor.execute(
                    "DELETE FROM proveedor WHERE id_proveedor = %s",
                    (id_proveedor,),
                )
                if cursor.rowcount == 0:
                    raise Http404("Proveedor no encontrado.")
                conexion.commit()
            except MySQLdb.IntegrityError as error:
                conexion.rollback()
                if error.args[0] == 1451:
                    error_eliminar = (
                        "No se puede eliminar este proveedor porque tiene ingresos o facturas "
                        "registradas en el sistema."
                    )
                else:
                    raise

            if error_eliminar:
                cursor.execute(
                    """
                    SELECT p.id_proveedor, p.rut, p.nombre, p.telefono, u.username AS registrado_por
                    FROM proveedor p
                    LEFT JOIN usuario u ON p.id_usuario = u.id_usuario
                    ORDER BY p.nombre ASC
                    """
                )
                listado = cursor.fetchall()
                form = ProveedorForm()
                return render(
                    request,
                    "proveedores/proveedores.html",
                    {
                        "form": form,
                        "proveedores": listado,
                        "error_eliminar": error_eliminar,
                    },
                    status=409,
                )

    return redirect("proveedores")
