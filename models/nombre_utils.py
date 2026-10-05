import re


SIGLAS = frozenset({'IT', 'TI', 'UPS', 'CEDI'})


def clave_nombre(value):
    return ' '.join((value or '').split()).casefold()


def normalizar_nombre(value):
    if not isinstance(value, str):
        return value
    value = ' '.join(value.split())
    return re.sub(
        r'[^\W\d_]+',
        lambda match: (
            match.group().upper() if match.group().upper() in SIGLAS
            else match.group().capitalize()
        ),
        value,
    )
