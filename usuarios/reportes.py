from contextlib import closing
from datetime import date

import MySQLdb
from MySQLdb.cursors import DictCursor
from django import forms
from django.conf import settings
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .views import solo_paulina


class RangoFechasForm(forms.Form):
    desde = forms.DateField(
        label="Desde",
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
    )
    hasta = forms.DateField(
        label="Hasta",
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
    )

    def clean(self):
        datos = super().clean()
        desde, hasta = datos.get("desde"), datos.get("hasta")
        if desde and hasta and desde > hasta:
            self.add_error("hasta", "La fecha final debe ser igual o posterior a la inicial.")
        return datos


def unidades_por_producto(desde, hasta):
    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor(DictCursor) as cursor:
            cursor.execute(
                """
                SELECT p.id_producto, p.nombre, SUM(d.cantidad) AS unidades
                FROM venta v
                JOIN detalle_venta d ON d.id_venta = v.id_venta
                JOIN producto p ON p.id_producto = d.id_producto
                WHERE v.fecha BETWEEN %s AND %s
                GROUP BY p.id_producto, p.nombre
                ORDER BY unidades DESC, p.nombre ASC, p.id_producto ASC
                """,
                (desde, hasta),
            )
            return cursor.fetchall()


def ventas_en_rango(desde, hasta):
    """Obtiene el registro de ventas realizadas dentro del rango seleccionado."""
    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor(DictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    v.id_venta,
                    DATE_FORMAT(v.fecha, '%%d/%%m/%%Y') AS fecha,
                    TIME_FORMAT(v.hora, '%%H:%%i') AS hora,
                    v.total,
                    v.medio_pago,
                    GROUP_CONCAT(
                        DISTINCT p.nombre
                        ORDER BY p.nombre ASC
                        SEPARATOR ', '
                    ) AS productos
                FROM venta v
                JOIN detalle_venta d ON d.id_venta = v.id_venta
                JOIN producto p ON p.id_producto = d.id_producto
                WHERE v.fecha BETWEEN %s AND %s
                GROUP BY v.id_venta, v.fecha, v.hora, v.total, v.medio_pago
                ORDER BY v.fecha DESC, v.hora DESC, v.id_venta DESC
                """,
                (desde, hasta),
            )
            return cursor.fetchall()


def escala_unidades(total):
    total = int(total)
    paso_minimo = (total + 4) // 5
    base = 10 ** (len(str(paso_minimo)) - 1)
    paso = next(base * factor for factor in (1, 2, 5, 10) if base * factor >= paso_minimo)
    tope = ((total + paso - 1) // paso) * paso
    return range(tope, -1, -paso)


@never_cache
@solo_paulina
@require_safe
def ranking_ventas(request):
    hoy = date.today()
    rango = request.GET if "desde" in request.GET or "hasta" in request.GET else {
        "desde": hoy.replace(day=1).isoformat(),
        "hasta": hoy.isoformat(),
    }
    form = RangoFechasForm(rango)
    if not form.is_valid():
        return render(request, "reportes/ranking.html", {"form": form})

    ventas = ventas_en_rango(form.cleaned_data["desde"], form.cleaned_data["hasta"])
    mas_vendidos = unidades_por_producto(form.cleaned_data["desde"], form.cleaned_data["hasta"])
    if not mas_vendidos:
        return render(request, "reportes/ranking.html", {"form": form, "ventas": ventas})

    menos_vendidos = sorted(mas_vendidos, key=lambda producto: producto["unidades"])
    mayor, menor = mas_vendidos[0], menos_vendidos[0]
    if len(mas_vendidos) == 1:
        comparacion = [("Único producto vendido", mayor["nombre"], mayor["unidades"])]
    elif mayor["unidades"] == menor["unidades"]:
        nombre = f"{len(mas_vendidos)} productos empatados"
        comparacion = [("Mismas unidades vendidas", nombre, mayor["unidades"])]
    else:
        comparacion = [
            ("Más vendido", mayor["nombre"], mayor["unidades"]),
            ("Menos vendido", menor["nombre"], menor["unidades"]),
        ]

    return render(
        request,
        "reportes/ranking.html",
        {
            "form": form,
            "ventas": ventas,
            "comparacion": comparacion,
            "escala": escala_unidades(mayor["unidades"]),
            "rankings": [
                ("Productos más vendidos", mas_vendidos),
                ("Productos menos vendidos", menos_vendidos),
            ],
        },
    )
