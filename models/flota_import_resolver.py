"""Resolución y alta automática de catálogos referenciados por nombre al importar.

Sin dependencias de Odoo para poder probar la lógica de forma aislada. El proveedor
debe implementar:

    tiene_padre(comodel) -> bool
    etiqueta_padre(comodel) -> str
    candidatos(comodel, texto) -> list[(padre_id, id)]   # incluye archivados
    crear(comodel, texto, padre_id) -> id                # lanza ErrorResolucion
"""


class ErrorResolucion(Exception):
    pass


def _texto(valor):
    if valor is None or valor is False:
        return ''
    return ' '.join(str(valor).split())


def _resolver_valor(proveedor, comodel, texto, padre_id, crear):
    """Devuelve (id, motivo); motivo solo informa cuando no se pudo resolver."""
    candidatos = proveedor.candidatos(comodel, texto)
    if proveedor.tiene_padre(comodel):
        etiqueta = proveedor.etiqueta_padre(comodel)
        if not padre_id:
            if len(candidatos) == 1:
                return candidatos[0][1], None
            if candidatos:
                return None, 'existe en varios; indique %s' % etiqueta
            return None, 'indique %s para crearlo' % etiqueta
        for candidato_padre, candidato_id in candidatos:
            if candidato_padre == padre_id:
                return candidato_id, None
    elif candidatos:
        return candidatos[0][1], None

    if not crear:
        return None, 'no existe'
    try:
        return proveedor.crear(comodel, texto, padre_id), None
    except ErrorResolucion as error:
        return None, str(error)


def resolver_referencias(fields, data, columnas, proveedor, padre_existente=None, crear=True):
    """Convierte las columnas de catálogo (nombre) en columnas ``campo/.id``.

    ``data`` se modifica en el sitio. Los valores que no se pueden resolver quedan como
    ``texto [motivo]`` para que Odoo los informe como error de esa fila en lugar de
    asignar un registro equivocado. Devuelve la nueva lista de campos.

    ``columnas`` mapea nombre de campo -> {'comodel': str, 'padre': campo|None}.
    ``padre_existente(fila, campo)`` aporta el padre del registro ya existente cuando
    el archivo no trae la columna del padre.
    """
    fields = list(fields)
    indices = {f: fields.index(f) for f in columnas if f in fields}
    if not indices:
        return fields

    orden = sorted(indices, key=lambda f: bool(columnas[f].get('padre')))
    for numero, fila in enumerate(data):
        resueltos = {}
        for campo in orden:
            i = indices[campo]
            if i >= len(fila):
                continue
            texto = _texto(fila[i])
            if not texto:
                fila[i] = ''
                continue
            padre = columnas[campo].get('padre')
            padre_id = None
            if padre:
                if padre in indices:
                    padre_id = resueltos.get(padre)
                elif padre_existente:
                    padre_id = padre_existente(numero, padre)
            id_, motivo = _resolver_valor(
                proveedor, columnas[campo]['comodel'], texto, padre_id, crear,
            )
            if id_:
                fila[i] = str(id_)
                resueltos[campo] = id_
            else:
                fila[i] = '%s [%s]' % (texto, motivo)

    for campo, i in indices.items():
        fields[i] = '%s/.id' % campo
    return fields
