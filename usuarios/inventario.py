from contextlib import closing

import MySQLdb
from MySQLdb.cursors import DictCursor
from django import forms
from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .views import _usuario_actual


class ProductoForm(forms.Form):
    nombre = forms.CharField(label="Nombre", max_length=150)
    precio_venta = forms.IntegerField(
        label="Precio de venta ($)",
        min_value=0,
        max_value=2147483647,
    )
    stock_actual = forms.IntegerField(
        label="Stock inicial",
        min_value=0,
        max_value=2147483647,
        initial=0,
    )


@require_http_methods(["GET", "POST"])
def productos(request, id_producto=None):
    if _usuario_actual(request) is None:
        return redirect("login")

    editando = id_producto is not None

    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor(DictCursor) as cursor:
            producto = None

            if editando:
                cursor.execute(
                    """
                    SELECT id_producto, nombre, precio_venta, stock_actual
                    FROM producto
                    WHERE id_producto = %s
                    """,
                    (id_producto,),
                )
                producto = cursor.fetchone()
                if producto is None:
                    raise Http404("Producto no encontrado.")

            form = ProductoForm(
                request.POST if request.method == "POST" else None,
                initial=producto,
            )
            if editando:
                del form.fields["stock_actual"]

            if request.method == "POST" and form.is_valid():
                datos = form.cleaned_data

                if editando:
                    cursor.execute(
                        """
                        UPDATE producto
                        SET nombre = %s, precio_venta = %s
                        WHERE id_producto = %s
                        """,
                        (datos["nombre"], datos["precio_venta"], id_producto),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO producto (nombre, precio_venta, stock_actual)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            datos["nombre"],
                            datos["precio_venta"],
                            datos["stock_actual"],
                        ),
                    )

                conexion.commit()
                return redirect("inventario")

            cursor.execute(
                """
                SELECT id_producto, nombre, precio_venta, stock_actual
                FROM producto
                ORDER BY nombre, id_producto
                """
            )
            listado = cursor.fetchall()

    return render(
        request,
        "inventario/productos.html",
        {
            "form": form,
            "productos": listado,
            "producto_editado": producto,
        },
    )


@require_POST
def eliminar_producto(request, id_producto):
    if _usuario_actual(request) is None:
        return redirect("login")

    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor() as cursor:
            try:
                cursor.execute(
                    "DELETE FROM producto WHERE id_producto = %s",
                    (id_producto,),
                )
                if cursor.rowcount == 0:
                    raise Http404("Producto no encontrado.")

                conexion.commit()
            except MySQLdb.IntegrityError as error:
                conexion.rollback()
                if error.args[0] != 1451:
                    raise

                return render(
                    request,
                    "inventario/productos.html",
                    {
                        "error_eliminar": (
                            "Este producto tiene ventas o ingresos registrados "
                            "y debe conservarse para mantener el historial."
                        ),
                    },
                    status=409,
                )

    return redirect("inventario")