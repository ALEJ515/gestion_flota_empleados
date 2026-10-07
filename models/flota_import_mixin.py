import uuid
from odoo import api, models

from .flota_import_resolver import normalizar_referencias
from .nombre_utils import clave_nombre


def _escapar_like(valor):
    return valor.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


class _ProveedorCatalogos:
    """Busca catálogos por nombre (incluidos los archivados) durante una importación."""

    def __init__(self, env):
        self.env = env
        self._indices = {}

    def _indice(self, comodel):
        if comodel not in self._indices:
            modelo = self.env[comodel].with_context(active_test=False)
            padre = modelo._flota_import_campo_padre
            indice = {}
            for rec in modelo.search([]):
                indice.setdefault(clave_nombre(rec.name), []).append(
                    (rec[padre].id if padre else 0, rec.id, rec.name)
                )
            self._indices[comodel] = indice
        return self._indices[comodel]

    def candidatos(self, comodel, texto):
        return list(self._indice(comodel).get(clave_nombre(texto), []))


class FlotaImportMixin(models.AbstractModel):
    """Hace que la importación desde Excel/CSV sea tolerante con archivos exportados:

    1. Ignora automáticamente las columnas que no se pueden importar (campos calculados,
       de solo lectura e historiales One2many como facturación, tendencia o totales), para
       que no haya que borrarlas del archivo antes de volver a importarlo.
    2. Si una fila no trae ID (o lo trae vacío) pero el registro ya existe, lo localiza
       por su clave natural (nombre, número de flota, etc.) y lo ACTUALIZA en lugar de
       intentar crearlo de nuevo y chocar con las validaciones de duplicados.
    3. Las referencias a catálogos (Departamento, Subdepartamento, Ubicación, Ruta, Plan,
       Marca...) se encuentran sin distinguir mayúsculas ni espacios, incluso si están
       archivadas, y los Subdepartamentos repetidos se resuelven con el Departamento de la
       fila. Lo que no existe NO se crea solo: Odoo ofrece sus opciones habituales
       (crear, omitir el registro o dejar el valor vacío).
    """
    _name = 'flota.import.mixin'
    _description = 'Importación con actualización automática (Flota)'

    # Catálogos cuyas referencias por nombre se normalizan al importar.
    _flota_import_catalogo = False
    # Campo del propio catálogo que lo acota (p. ej. el Departamento de un Subdepartamento).
    _flota_import_campo_padre = None

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        # Odoo resuelve las referencias de importación con name_search(operator='=').
        if name and operator == '=' and 'nombre_busqueda' not in self._fields:
            encontrados = self.with_context(active_test=False).search(
                [('name', '=ilike', _escapar_like(' '.join(name.split())))] + list(domain or []),
                limit=limit or None,
            )
            return [(rec.id, rec.display_name) for rec in encontrados]
        return super().name_search(name=name, domain=domain, operator=operator, limit=limit)

    @api.model
    def _flota_import_campo_ignorado(self, fname):
        if fname in ('id', '.id'):
            return False
        field = self._fields.get(fname)
        if not field:
            return False
        if field.type == 'one2many':
            return True
        if field.compute and not field.inverse:
            return True
        return bool(field.readonly)

    @api.model
    def _flota_import_buscar_existente(self, fila):
        """Clave natural por defecto: el nombre (sin distinguir mayúsculas)."""
        nombre = fila.get('name')
        if 'name' in self._fields and isinstance(nombre, str) and nombre.strip():
            nombre = _escapar_like(' '.join(nombre.split()))
            encontrados = self.with_context(active_test=False).search(
                [('name', '=ilike', nombre)], limit=2)
            if len(encontrados) == 1:
                return encontrados
        return self.browse()

    def _flota_import_xmlid(self):
        self.ensure_one()
        existentes = self._get_external_ids().get(self.id)
        if existentes:
            return existentes[0]
        nombre = '%s_%s_%s' % (self._table, self.id, uuid.uuid4().hex[:8])
        self.env['ir.model.data'].sudo().create({
            'module': '__export__',
            'name': nombre,
            'model': self._name,
            'res_id': self.id,
        })
        return '__export__.%s' % nombre

    @api.model
    def _flota_import_registro_xmlid(self, xmlid):
        """Registro de este modelo para un ID externo del archivo; vacío si no existe aquí. Un ID
        inexistente (p. ej. exportado desde otro Odoo) se trata como fila sin ID para que se
        busque el registro por su clave natural en lugar de duplicarlo."""
        xmlid = str(xmlid).strip()
        if '.' not in xmlid:
            xmlid = '__import__.%s' % xmlid
        try:
            registro = self.env.ref(xmlid, raise_if_not_found=False)
        except ValueError:
            return self.browse()
        if registro and registro._name == self._name:
            return registro
        return self.browse()

    @api.model
    def _flota_import_xmlid_valido(self, xmlid):
        return bool(self._flota_import_registro_xmlid(xmlid))

    @api.model
    def _flota_import_columnas_catalogo(self, fields):
        columnas = {}
        for fname in fields:
            if '/' in fname or fname in ('id', '.id'):
                continue
            field = self._fields.get(fname)
            if not field or field.type != 'many2one':
                continue
            comodelo = self.env[field.comodel_name]
            if getattr(comodelo, '_flota_import_catalogo', False):
                columnas[fname] = {
                    'comodel': field.comodel_name,
                    'padre': comodelo._flota_import_campo_padre or None,
                }
        return columnas

    @staticmethod
    def _flota_import_tiene_valor(valor):
        if valor is None or valor is False:
            return False
        return bool(str(valor).strip())

    @api.model
    def load(self, fields, data):
        if self.env.context.get('flota_import_sin_ajustes'):
            return super().load(fields, data)

        fields = list(fields)
        data = [list(fila) for fila in data]

        indices = [i for i, f in enumerate(fields)
                   if not self._flota_import_campo_ignorado(f.split('/')[0])]
        if len(indices) != len(fields):
            fields = [fields[i] for i in indices]
            data = [[fila[i] if i < len(fila) else '' for i in indices] for fila in data]
            # Las filas extra que solo traían líneas de historial (One2many) quedan vacías.
            data = [fila for fila in data if any(self._flota_import_tiene_valor(v) for v in fila)]

        registros = {}
        if fields and '.id' not in fields:
            if 'id' in fields:
                id_idx = fields.index('id')
            else:
                fields.append('id')
                id_idx = len(fields) - 1
                for fila in data:
                    fila.append('')
            usados = set()
            for numero, fila in enumerate(data):
                if self._flota_import_tiene_valor(fila[id_idx]):
                    existente = self._flota_import_registro_xmlid(fila[id_idx])
                    if existente:
                        registros[numero] = existente
                        continue
                valores = {f: v for f, v in zip(fields, fila) if '/' not in f}
                registro = self._flota_import_buscar_existente(valores)
                if registro and registro.id not in usados:
                    usados.add(registro.id)
                    fila[id_idx] = registro._flota_import_xmlid()
                    registros[numero] = registro

        def padre_existente(numero, campo):
            registro = registros.get(numero)
            if registro and campo in registro._fields and registro[campo]:
                return registro[campo].id, registro[campo].name
            return None

        columnas = {} if self.env.context.get('flota_import_sin_referencias') \
            else self._flota_import_columnas_catalogo(fields)
        if columnas:
            fields, data = normalizar_referencias(
                fields, data, columnas, _ProveedorCatalogos(self.env),
                padre_existente=padre_existente,
            )
        return super().load(fields, data)
