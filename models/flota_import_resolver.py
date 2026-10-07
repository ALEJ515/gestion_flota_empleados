"""Normalización de referencias a catálogos por nombre al importar (sin dependencias de Odoo).

No crea ni descarta nada: solo reescribe el texto de la celda con un nombre que Odoo pueda
resolver sin ambigüedad, para que sus opciones nativas (crear, omitir, dejar vacío) sigan
disponibles cuando el valor realmente no existe.

El proveedor debe implementar:

    candidatos(comodel, texto) -> list[(padre_id, id, nombre)]   # incluye archivados
"""

SEPARADOR_PADRE = ' / '


def _texto(valor):
    if valor is None or valor is False:
        return ''
    return ' '.join(str(valor).split())


def normalizar_referencias(fields, data, columnas, proveedor, padre_existente=None):
    """Devuelve ``(fields, data)`` con el texto de las columnas de catálogo normalizado.

    - Un registro existente se escribe con su nombre exacto (mayúsculas y espacios correctos).
    - Un registro con padre (Subdepartamento) se escribe ``Padre / Nombre`` cuando el padre es
      conocido: por la columna del padre en la fila o, si no viene, por el registro existente.
      Así un nombre repetido en varios padres se resuelve en el correcto, y si no existe, Odoo
      puede crearlo dentro de ese padre.
    - Lo desconocido queda tal cual para que Odoo lo informe con sus opciones habituales.
    - Las columnas con padre se mueven después de la columna del padre, para que un padre
      creado en la misma importación ya exista cuando se resuelva el hijo.

    ``columnas`` mapea campo -> {'comodel': str, 'padre': campo|None}.
    ``padre_existente(fila, campo)`` devuelve ``(id, nombre)`` del padre del registro existente.
    """
    fields = list(fields)
    data = [list(fila) for fila in data]
    indices = {f: fields.index(f) for f in columnas if f in fields}
    if not indices:
        return fields, data

    hijos = [f for f in indices if columnas[f].get('padre') and columnas[f]['padre'] in indices]
    orden = sorted(indices, key=lambda f: bool(columnas[f].get('padre')))
    for numero, fila in enumerate(data):
        encontrados = {}
        textos = {}
        for campo in orden:
            i = indices[campo]
            if i >= len(fila):
                continue
            texto = _texto(fila[i])
            fila[i] = texto
            if not texto:
                continue
            textos[campo] = texto
            comodel = columnas[campo]['comodel']
            padre = columnas[campo].get('padre')
            candidatos = proveedor.candidatos(comodel, texto)

            if not padre:
                if candidatos:
                    _, id_, nombre = candidatos[0]
                    fila[i] = nombre
                    encontrados[campo] = (id_, nombre)
                continue

            padre_id = padre_nombre = None
            if padre in indices:
                if padre in encontrados:
                    padre_id, padre_nombre = encontrados[padre]
                else:
                    padre_nombre = textos.get(padre)
            elif padre_existente:
                datos = padre_existente(numero, padre)
                if datos:
                    padre_id, padre_nombre = datos
            if not padre_nombre:
                continue
            nombre = texto
            for candidato_padre, _, candidato_nombre in candidatos:
                if padre_id and candidato_padre == padre_id:
                    nombre = candidato_nombre
                    break
            fila[i] = '%s%s%s' % (padre_nombre, SEPARADOR_PADRE, nombre)

    if hijos:
        resto = [i for f, i in sorted(indices.items(), key=lambda x: x[1]) if f not in hijos]
        movidos = [indices[f] for f in hijos]
        fijas = [i for i in range(len(fields)) if i not in indices.values()]
        nuevo_orden = sorted(fijas + resto) + sorted(movidos)
        fields = [fields[i] for i in nuevo_orden]
        data = [[fila[i] if i < len(fila) else '' for i in nuevo_orden] for fila in data]
    return fields, data
