from contextlib import closing
from datetime import date
import json
import re

import MySQLdb
from MySQLdb.cursors import DictCursor
from django.conf import settings
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .views import _usuario_actual, es_paulina


def listar_proveedores_activos():
    """Retorna la lista de proveedores disponibles para el selector de factura."""
    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor(DictCursor) as cursor:
            cursor.execute(
                """
                SELECT id_proveedor, rut, nombre, telefono
                FROM proveedor
                ORDER BY nombre ASC
                """
            )
            return cursor.fetchall()


def listar_productos_para_ingreso():
    """Retorna productos activos con su stock actual para poblar el catálogo de compras."""
    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor(DictCursor) as cursor:
            cursor.execute(
                """
                SELECT id_producto, nombre, precio_venta, stock_actual
                FROM producto
                WHERE estado = 1
                ORDER BY nombre ASC
                """
            )
            return [
                {
                    "id_producto": row["id_producto"],
                    "nombre": row["nombre"],
                    "precio_venta": int(row["precio_venta"]),
                    "stock_actual": int(row["stock_actual"]),
                }
                for row in cursor.fetchall()
            ]


def existe_factura_proveedor(id_proveedor, numero_factura, cursor=None):
    """
    Verifica si ya existe una factura registrada con el número dado para el proveedor especificado.
    Retorna (True, id_ingreso) si existe, o (False, None) si no existe.
    """
    num_limpio = str(numero_factura or "").strip()
    if not num_limpio or not id_proveedor:
        return False, None

    patron1 = f"Factura N° {num_limpio}"
    patron2 = f"Factura N° {num_limpio} - %"
    patron3 = f"Factura N° {num_limpio} %"
    regex = rf"^Factura\s*N[°oº]?\s*{re.escape(num_limpio)}(\s*-\s*|\s|$)"

    sql = """
        SELECT id_ingreso, observacion 
        FROM ingreso_mercancia 
        WHERE id_proveedor = %s 
          AND (
              observacion = %s 
              OR observacion LIKE %s 
              OR observacion LIKE %s
              OR observacion REGEXP %s
          )
        LIMIT 1
    """

    if cursor is not None:
        cursor.execute(sql, (id_proveedor, patron1, patron2, patron3, regex))
        res = cursor.fetchone()
        if res:
            id_ingreso = res["id_ingreso"] if isinstance(res, dict) else res[0]
            return True, id_ingreso
        return False, None
    else:
        with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
            with conexion.cursor(DictCursor) as cur:
                cur.execute(sql, (id_proveedor, patron1, patron2, patron3, regex))
                res = cur.fetchone()
                if res:
                    return True, res["id_ingreso"]
                return False, None


def registrar_ingreso_factura_atomica(id_proveedor, numero_factura, fecha, observacion, items):
    """
    Transacción atómica en MariaDB/MySQL que:
    1. Inserta en `ingreso_mercancia` (proveedor, fecha, observación con N° factura).
    2. Inserta cada ítem en `detalle_ingreso` (producto, cantidad, precio_compra).
    3. Suma las unidades al `stock_actual` en la tabla `producto`.
    """
    if not items:
        raise ValueError("Debe incluir al menos un producto en el detalle de la factura.")

    num_factura = str(numero_factura or "").strip()
    if not num_factura:
        raise ValueError("El número de factura es obligatorio.")

    if not fecha:
        fecha = date.today().strftime("%Y-%m-%d")

    obs_texto = str(observacion or "").strip()
    if obs_texto:
        observacion_final = f"Factura N° {num_factura} - {obs_texto}"[:255]
    else:
        observacion_final = f"Factura N° {num_factura}"[:255]

    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        try:
            conexion.begin()
            with conexion.cursor() as cursor:
                # Validar existencia de proveedor si se indicó
                nombre_proveedor = "el proveedor"
                if id_proveedor:
                    cursor.execute(
                        "SELECT nombre FROM proveedor WHERE id_proveedor = %s",
                        (id_proveedor,),
                    )
                    prov = cursor.fetchone()
                    if prov is None:
                        raise ValueError("El proveedor seleccionado no existe.")
                    nombre_proveedor = prov[0] if isinstance(prov, (tuple, list)) else prov.get("nombre", "el proveedor")

                # Validar que no se duplique la factura para este proveedor
                duplicada, id_existente = existe_factura_proveedor(id_proveedor, num_factura, cursor=cursor)
                if duplicada:
                    raise ValueError(
                        f"Ya existe una factura registrada con el N° '{num_factura}' para {nombre_proveedor} (Comprobante #{id_existente})."
                    )

                # 1. Registrar cabecera del ingreso de mercadería
                cursor.execute(
                    """
                    INSERT INTO ingreso_mercancia (id_proveedor, fecha, observacion)
                    VALUES (%s, %s, %s)
                    """,
                    (id_proveedor if id_proveedor else None, fecha, observacion_final),
                )
                id_ingreso = cursor.lastrowid

                total_unidades = 0
                total_costo = 0

                # 2. Registrar detalles y sumar unidades al stock
                for item in items:
                    id_producto = int(item["id_producto"])
                    cantidad = int(item["cantidad"])
                    precio_compra = int(item.get("precio_compra", 0))

                    if cantidad <= 0:
                        raise ValueError("La cantidad debe ser mayor a 0.")
                    if precio_compra < 0:
                        raise ValueError("El precio de compra no puede ser negativo.")

                    # Verificar existencia del producto
                    cursor.execute(
                        "SELECT nombre, stock_actual FROM producto WHERE id_producto = %s FOR UPDATE",
                        (id_producto,),
                    )
                    prod = cursor.fetchone()
                    if prod is None:
                        raise ValueError(f"El producto con ID {id_producto} no existe.")

                    # Insertar detalle de ingreso
                    cursor.execute(
                        """
                        INSERT INTO detalle_ingreso (id_ingreso, id_producto, cantidad, precio_compra)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (id_ingreso, id_producto, cantidad, precio_compra),
                    )

                    # 3. Sumar las unidades al stock del producto
                    cursor.execute(
                        """
                        UPDATE producto
                        SET stock_actual = stock_actual + %s
                        WHERE id_producto = %s
                        """,
                        (cantidad, id_producto),
                    )

                    total_unidades += cantidad
                    total_costo += cantidad * precio_compra

            conexion.commit()
            return {
                "id_ingreso": id_ingreso,
                "numero_factura": num_factura,
                "total_unidades": total_unidades,
                "total_costo": total_costo,
            }
        except Exception:
            conexion.rollback()
            raise


@require_http_methods(["GET"])
def nuevo_ingreso(request):
    """Renderiza la pantalla para registrar una factura con su detalle de productos."""
    usuario = _usuario_actual(request)
    if usuario is None:
        return redirect("login")

    proveedores = listar_proveedores_activos()
    productos = listar_productos_para_ingreso()

    return render(
        request,
        "ingresos/nuevo_ingreso.html",
        {
            "es_paulina": es_paulina(usuario),
            "proveedores": proveedores,
            "productos": productos,
            "fecha_hoy": date.today().strftime("%Y-%m-%d"),
        },
    )


@require_POST
def api_confirmar_ingreso(request):
    """Endpoint API para registrar la factura de compra y sumar el stock de forma atómica."""
    if _usuario_actual(request) is None:
        return JsonResponse(
            {"ok": False, "error": "Debes iniciar sesión para registrar una factura."},
            status=401,
        )

    try:
        data = json.loads(request.body)
        id_proveedor = data.get("id_proveedor")
        numero_factura = data.get("numero_factura")
        fecha = data.get("fecha")
        observacion = data.get("observacion", "")
        items = data.get("items", [])

        if not id_proveedor:
            return JsonResponse({"ok": False, "error": "Debes seleccionar un proveedor."}, status=400)
        if not numero_factura:
            return JsonResponse({"ok": False, "error": "El número de factura es obligatorio."}, status=400)
        if not items:
            return JsonResponse({"ok": False, "error": "Debes agregar al menos un producto a la factura."}, status=400)

        resultado = registrar_ingreso_factura_atomica(
            id_proveedor=id_proveedor,
            numero_factura=numero_factura,
            fecha=fecha,
            observacion=observacion,
            items=items,
        )

        return JsonResponse(
            {
                "ok": True,
                "mensaje": (
                    f"Factura N° {resultado['numero_factura']} registrada con éxito. "
                    f"Se ingresaron {resultado['total_unidades']} unidades al stock."
                ),
                "id_ingreso": resultado["id_ingreso"],
                "total_unidades": resultado["total_unidades"],
                "total_costo": resultado["total_costo"],
            }
        )
    except ValueError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse(
            {"ok": False, "error": f"Error interno al procesar el ingreso: {str(e)}"},
            status=500,
        )


@require_http_methods(["GET"])
def api_validar_factura(request):
    """Endpoint para comprobar si ya existe una factura para un proveedor antes de enviarla."""
    if _usuario_actual(request) is None:
        return JsonResponse({"ok": False, "error": "No autorizado."}, status=401)

    id_proveedor = request.GET.get("id_proveedor")
    numero_factura = request.GET.get("numero_factura", "").strip()

    if not id_proveedor or not numero_factura:
        return JsonResponse({"ok": True, "duplicada": False})

    try:
        id_prov = int(id_proveedor)
        duplicada, id_existente = existe_factura_proveedor(id_prov, numero_factura)
        return JsonResponse(
            {
                "ok": True,
                "duplicada": duplicada,
                "id_ingreso": id_existente,
                "mensaje": (
                    f"Ya existe una factura registrada con el N° '{numero_factura}' para este proveedor (Comprobante #{id_existente})."
                    if duplicada
                    else ""
                ),
            }
        )
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@require_http_methods(["GET"])
def historial_ingresos(request):
    """Consulta el historial de facturas e ingresos de mercadería."""
    usuario = _usuario_actual(request)
    if usuario is None:
        return redirect("login")

    busqueda = request.GET.get("q", "").strip()

    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor(DictCursor) as cursor:
            query = """
                SELECT 
                    i.id_ingreso,
                    i.fecha,
                    i.observacion,
                    p.nombre AS proveedor_nombre,
                    p.rut AS proveedor_rut,
                    COALESCE(SUM(d.cantidad), 0) AS total_unidades,
                    COALESCE(SUM(d.cantidad * d.precio_compra), 0) AS total_costo
                FROM ingreso_mercancia i
                LEFT JOIN proveedor p ON i.id_proveedor = p.id_proveedor
                LEFT JOIN detalle_ingreso d ON i.id_ingreso = d.id_ingreso
            """
            params = []
            if busqueda:
                query += " WHERE i.observacion LIKE %s OR p.nombre LIKE %s OR p.rut LIKE %s "
                termino = f"%{busqueda}%"
                params = [termino, termino, termino]

            query += """
                GROUP BY i.id_ingreso, i.fecha, i.observacion, p.nombre, p.rut
                ORDER BY i.fecha DESC, i.id_ingreso DESC
            """
            cursor.execute(query, params)
            ingresos = cursor.fetchall()

    return render(
        request,
        "ingresos/historial.html",
        {
            "es_paulina": es_paulina(usuario),
            "ingresos": ingresos,
            "busqueda": busqueda,
        },
    )


@require_http_methods(["GET"])
def detalle_ingreso_view(request, id_ingreso):
    """Muestra el detalle y los productos de una factura o ingreso específico."""
    if _usuario_actual(request) is None:
        return redirect("login")

    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor(DictCursor) as cursor:
            cursor.execute(
                """
                SELECT 
                    i.id_ingreso,
                    i.fecha,
                    i.observacion,
                    p.nombre AS proveedor_nombre,
                    p.rut AS proveedor_rut,
                    p.telefono AS proveedor_telefono
                FROM ingreso_mercancia i
                LEFT JOIN proveedor p ON i.id_proveedor = p.id_proveedor
                WHERE i.id_ingreso = %s
                """,
                (id_ingreso,),
            )
            ingreso = cursor.fetchone()
            if ingreso is None:
                raise Http404("Comprobante de ingreso no encontrado.")

            cursor.execute(
                """
                SELECT 
                    d.id_detalle_ingreso,
                    d.cantidad,
                    d.precio_compra,
                    (d.cantidad * d.precio_compra) AS subtotal,
                    pr.nombre AS producto_nombre,
                    pr.stock_actual
                FROM detalle_ingreso d
                JOIN producto pr ON d.id_producto = pr.id_producto
                WHERE d.id_ingreso = %s
                ORDER BY pr.nombre ASC
                """,
                (id_ingreso,),
            )
            detalles = cursor.fetchall()

    total_unidades = sum(d["cantidad"] for d in detalles)
    total_costo = sum(d["subtotal"] for d in detalles)

    return render(
        request,
        "ingresos/detalle.html",
        {
            "ingreso": ingreso,
            "detalles": detalles,
            "total_unidades": total_unidades,
            "total_costo": total_costo,
        },
    )
