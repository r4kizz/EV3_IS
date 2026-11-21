from contextlib import closing

import MySQLdb
from django.conf import settings


def listar_productos_disponibles() -> list[dict]:
    """Obtiene todos los productos activos con stock mayor a 0."""
    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor() as cursor:
            cursor.execute(
                """
                SELECT id_producto, nombre, precio_venta, stock_actual
                FROM producto
                WHERE estado = 1 AND stock_actual > 0
                ORDER BY nombre ASC
                """
            )
            rows = cursor.fetchall()

    return [
        {
            "id_producto": row[0],
            "nombre": row[1],
            "precio_venta": int(row[2]),
            "stock_actual": int(row[3]),
        }
        for row in rows
    ]


def registrar_venta_atomica(items: list[dict], medio_pago: str) -> dict:
    """
    Valida stock, inserta en `venta` y `detalle_venta`, y descuenta `stock_actual`
    dentro de una única transacción atómica en MariaDB.
    """
    if not items:
        raise ValueError("El carrito de venta está vacío.")

    medios_validos = {"Efectivo", "Débito", "Crédito", "Transferencia"}
    if medio_pago not in medios_validos:
        raise ValueError("Medio de pago no válido.")

    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        try:
            conexion.begin()
            with conexion.cursor() as cursor:
                total_venta = 0
                detalles_validados = []

                for item in items:
                    id_producto = int(item["id_producto"])
                    cantidad = int(item["cantidad"])

                    if cantidad <= 0:
                        raise ValueError("La cantidad debe ser mayor a 0.")

                    cursor.execute(
                        """
                        SELECT nombre, precio_venta, stock_actual, estado
                        FROM producto
                        WHERE id_producto = %s
                        FOR UPDATE
                        """,
                        [id_producto],
                    )
                    prod = cursor.fetchone()

                    if not prod:
                        raise ValueError(f"El producto ID {id_producto} no existe.")

                    nombre, precio_venta, stock_actual, estado = prod

                    if estado != 1:
                        raise ValueError(f"El producto '{nombre}' se encuentra inactivo.")

                    if stock_actual < cantidad:
                        raise ValueError(
                            f"Stock insuficiente para '{nombre}'. Disponible: {stock_actual}, solicitado: {cantidad}."
                        )

                    subtotal = int(precio_venta) * cantidad
                    total_venta += subtotal
                    detalles_validados.append(
                        {
                            "id_producto": id_producto,
                            "cantidad": cantidad,
                            "subtotal": subtotal,
                        }
                    )

                cursor.execute(
                    """
                    INSERT INTO venta (fecha, hora, total, medio_pago)
                    VALUES (CURDATE(), CURTIME(), %s, %s)
                    """,
                    [total_venta, medio_pago],
                )
                id_venta = cursor.lastrowid

                for det in detalles_validados:
                    cursor.execute(
                        """
                        INSERT INTO detalle_venta (id_venta, id_producto, cantidad, subtotal)
                        VALUES (%s, %s, %s, %s)
                        """,
                        [id_venta, det["id_producto"], det["cantidad"], det["subtotal"]],
                    )

                    cursor.execute(
                        """
                        UPDATE producto
                        SET stock_actual = stock_actual - %s
                        WHERE id_producto = %s
                        """,
                        [det["cantidad"], det["id_producto"]],
                    )

            conexion.commit()
        except Exception:
            conexion.rollback()
            raise

    return {"id_venta": id_venta, "total": total_venta}