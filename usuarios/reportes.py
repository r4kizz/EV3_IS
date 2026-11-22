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

    mas_vendidos = unidades_por_producto(form.cleaned_data["desde"], form.cleaned_data["hasta"])
    menos_vendidos = sorted(mas_vendidos, key=lambda producto: producto["unidades"])
    return render(
        request,
        "reportes/ranking.html",
        {
            "form": form,
            "rankings": [
                ("Productos más vendidos", mas_vendidos),
                ("Productos menos vendidos", menos_vendidos),
            ] if mas_vendidos else [],
        },
    )
