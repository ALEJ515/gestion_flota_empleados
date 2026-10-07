import logging
import uuid
from odoo import api, models, _
from odoo.exceptions import AccessError

from .flota_import_resolver import ErrorResolucion, resolver_referencias
from .nombre_utils import clave_nombre

_logger = logging.getLogger(__name__)

MAX_NOMBRES_AVISO = 15


def _escapar_like(valor):
    return valor.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


class _ProveedorCatalogos:
    """Busca (incluso archivados) y crea catálogos referenciados por nombre durante una importación."""

    def __init__(self, env):
        self.env = env
        self._indices = {}
        self.creados = {}

    def tiene_padre(self, comodel):
        return bool(self.env[comodel]._flota_import_campo_padre)

    def etiqueta_padre(self, comodel):
        modelo = self.env[comodel]
        return modelo._fields[modelo._flota_import_campo_padre].string

    def _indice(self, comodel):
        if comodel not in self._indices:
            modelo = self.env[comodel].with_context(active_test=False)
            padre = modelo._flota_import_campo_padre
            indice = {}
            for rec in modelo.search([]):
                indice.setdefault(clave_nombre(rec.name), []).append(
                    (rec[padre].id if padre else 0, rec.id)
                )
            self._indices[comodel] = indice
        return self._indices[comodel]

    def candidatos(self, comodel, texto):
        return list(self._indice(comodel).get(clave_nombre(texto), []))

    def crear(self, comodel, texto, padre_id):
        modelo = self.env[comodel].with_context(
            tracking_disable=True, mail_create_nolog=True, mail_create_nosubscribe=True,
        )
        try:
            with self.env.cr.savepoint():
                rec = modelo.create(modelo._flota_import_valores_creacion(texto, padre_id))
        except AccessError:
            raise ErrorResolucion(_('no tiene permiso para crearlo'))
        except Exception as error:  # noqa: BLE001
            raise ErrorResolucion(_('no se pudo crear: %s') % str(error)[:80])
        con_padre = bool(modelo._flota_import_campo_padre)
        self._indice(comodel).setdefault(clave_nombre(rec.name), []).append(
            (padre_id if con_padre else 0, rec.id)
        )
        self.creados.setdefault(modelo._description, []).append(rec.display_name)
        return rec.id


class FlotaImportMixin(models.AbstractModel):
    """Hace que la importación desde Excel/CSV sea tolerante con archivos exportados:

    1. Ignora automáticamente las columnas que no se pueden importar (campos calculados,
       de solo lectura e historiales One2many como facturación, tendencia o totales), para
       que no haya que borrarlas del archivo antes de volver a importarlo.
    2. Si una fila no trae ID (o lo trae vacío) pero el registro ya existe, lo localiza
       por su clave natural (nombre, número de flota, etc.) y lo ACTUALIZA en lugar de
       intentar crearlo de nuevo y chocar con las validaciones de duplicados.
    3. Las referencias a catálogos (Departamento, Subdepartamento, Ubicación, Ruta, Plan,
       Marca...) se resuelven por nombre sin distinguir mayúsculas, incluso si están
       archivadas, usando el Departamento de la fila para los Subdepartamentos repetidos.
       Si no existen, se crean automáticamente (se informa en un aviso).
    """
    _name = 'flota.import.mixin'
    _description = 'Importación con actualización automática (Flota)'

    # Los catálogos que se pueden crear por nombre al importar lo activan en True.
    _flota_import_autocrear = False
    # Campo del propio catálogo que lo acota (p. ej. el Departamento de un Subdepartamento).
    _flota_import_campo_padre = None

    @api.model
    def _flota_import_valores_creacion(self, texto, padre_id=None):
        valores = {'name': texto}
        if self._flota_import_campo_padre and padre_id:
            valores[self._flota_import_campo_padre] = padre_id
        return valores

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
            if getattr(comodelo, '_flota_import_autocrear', False):
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
    def _flota_import_aviso_creados(self, creados):
        partes = []
        for tipo, nombres in creados.items():
            mostrados = ', '.join(nombres[:MAX_NOMBRES_AVISO])
            if len(nombres) > MAX_NOMBRES_AVISO:
                mostrados += _(' y %s más') % (len(nombres) - MAX_NOMBRES_AVISO)
            partes.append('%s: %s' % (tipo, mostrados))
        return _('Se crean automáticamente porque no existían: %s', '; '.join(partes))

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
            if registro and campo in registro._fields:
                return registro[campo].id
            return None

        proveedor = _ProveedorCatalogos(self.env)
        columnas = {} if self.env.context.get('flota_import_sin_referencias') \
            else self._flota_import_columnas_catalogo(fields)
        # Las altas automáticas se deshacen si la importación termina con errores.
        savepoint = self.env.cr.savepoint()
        try:
            if columnas:
                fields = resolver_referencias(
                    fields, data, columnas, proveedor, padre_existente=padre_existente,
                    crear=not self.env.context.get('flota_import_no_crear'),
                )
            resultado = super().load(fields, data)
        except Exception:
            savepoint.close(rollback=True)
            raise
        con_errores = resultado.get('ids') is False
        savepoint.close(rollback=con_errores)

        if proveedor.creados and not con_errores:
            _logger.info('Importación %s: catálogos creados: %s', self._name, proveedor.creados)
            resultado['messages'].append({
                'type': 'warning',
                'message': self._flota_import_aviso_creados(proveedor.creados),
            })
        return resultado
