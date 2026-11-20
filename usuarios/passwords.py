from base64 import b64encode
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from secrets import token_hex

_ITERACIONES = 1_000_000


def cumple_politica(password):
    return (
        8 <= len(password) <= 4096
        and any(c.isdecimal() for c in password)
        and any(c.isupper() for c in password)
        and any(c.islower() for c in password)
        and any(not c.isalnum() and not c.isspace() for c in password)
    )


def _derivar(password, sal, iteraciones):
    resultado = pbkdf2_hmac("sha256", password.encode(), sal.encode(), iteraciones)
    return b64encode(resultado).decode("ascii")


def generar_hash(password):
    sal = token_hex(16)
    return f"pbkdf2_sha256${_ITERACIONES}${sal}${_derivar(password, sal, _ITERACIONES)}"


def verificar_password(password, guardada):
    if not guardada:
        _derivar(password, "cuenta-inexistente", _ITERACIONES)
        return False

    algoritmo, _, datos = guardada.partition("$")
    if algoritmo != "pbkdf2_sha256":
        return False

    try:
        iteraciones, sal, esperado = datos.split("$")
        calculado = _derivar(password, sal, int(iteraciones))
        return compare_digest(calculado, esperado)
    except (ValueError, OverflowError):
        return False
