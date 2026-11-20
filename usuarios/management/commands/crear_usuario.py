from getpass import getpass

from MySQLdb import IntegrityError
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from usuarios.database import insertar_usuario
from usuarios.passwords import cumple_politica, generar_hash


class Command(BaseCommand):
    help = "Crea una cuenta en la tabla usuario del almacén."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("correo")

    def handle(self, *args, **options):
        username = options["username"].strip()
        correo = options["correo"].strip()
        if not 1 <= len(username) <= 100 or len(correo) > 150:
            raise CommandError("Revisa la longitud del usuario y el correo.")

        password = getpass("Contraseña: ")
        if password != getpass("Confirma la contraseña: "):
            raise CommandError("Las contraseñas no coinciden.")

        try:
            validate_email(correo)
            if not cumple_politica(password):
                raise CommandError(
                    "Usa al menos 8 caracteres e incluye números, mayúsculas, minúsculas y símbolos."
                )
            insertar_usuario(username, correo, generar_hash(password))
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from error
        except IntegrityError as error:
            if error.args[0] != 1062:
                raise
            raise CommandError("El nombre de usuario o correo ya está registrado.") from error

        self.stdout.write(self.style.SUCCESS(f"Cuenta creada: {username}"))
