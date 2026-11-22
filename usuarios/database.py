from contextlib import closing

import MySQLdb
from MySQLdb.cursors import DictCursor
from django.conf import settings

from .passwords import verificar_password


def buscar_usuario(id_usuario):
    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor(DictCursor) as cursor:
            cursor.execute(
                "SELECT id_usuario, username, correo, rol FROM usuario WHERE id_usuario = %s "
                "AND (bloqueado_hasta IS NULL OR bloqueado_hasta <= UTC_TIMESTAMP())",
                (id_usuario,),
            )
            return cursor.fetchone()


def insertar_usuario(username, correo, password_hash):
    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor() as cursor:
            cursor.execute(
                "INSERT INTO usuario (username, correo, password) VALUES (%s, %s, %s)",
                (username, correo, password_hash),
            )
        conexion.commit()


def autenticar_usuario(username, password):
    with closing(MySQLdb.connect(**settings.ALMACEN_DB)) as conexion:
        with conexion.cursor(DictCursor) as cursor:
            cursor.execute(
                "SELECT id_usuario, password, intentos_fallidos, bloqueado_hasta, "
                "bloqueado_hasta > UTC_TIMESTAMP() AS bloqueo_vigente "
                "FROM usuario WHERE username = %s FOR UPDATE",
                (username,),
            )
            usuario = cursor.fetchone()
            if usuario is None:
                verificar_password(password, None)
                return None, False
            if usuario["bloqueo_vigente"]:
                return None, True

            valido = verificar_password(password, usuario["password"])
            intentos_previos = 0 if usuario["bloqueado_hasta"] else usuario["intentos_fallidos"]
            intentos = 0 if valido else intentos_previos + 1
            bloqueado = intentos >= 3
            cursor.execute(
                "UPDATE usuario SET intentos_fallidos = %s, bloqueado = %s, "
                "bloqueado_hasta = CASE WHEN %s THEN UTC_TIMESTAMP() + INTERVAL 1 MINUTE END "
                "WHERE id_usuario = %s",
                (intentos, bloqueado, bloqueado, usuario["id_usuario"]),
            )
        conexion.commit()
        return (usuario["id_usuario"] if valido else None), bloqueado
