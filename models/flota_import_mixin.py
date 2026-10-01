import uuid
from odoo import api, models


class FlotaImportMixin(models.AbstractModel):
    """Hace que la importación desde Excel/CSV sea tolerante con archivos exportados:

    1. Ignora automáticamente las columnas que no se pueden importar (campos calculados,
       de solo lectura e historiales One2many como facturación, tendencia o totales), para
       que no haya que borrarlas del archivo antes de volver a importarlo.
    2. Si una fila no trae ID (o lo trae vacío) pero el registro ya existe, lo localiza
       por su clave natural (nombre, número de flota, etc.) y lo ACTUALIZA en lugar de
       intentar crearlo de nuevo y chocar con las validaciones de duplicados.
    """
    _name = 'flota.import.mixin'
    _description = 'Importación con actualización automática (Flota)'

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
            encontrados = self.with_context(active_test=False).search(
                [('name', '=ilike', nombre.strip())], limit=2)
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
    def _flota_import_xmlid_valido(self, xmlid):
        """True si el ID del archivo existe en esta base de datos. Un ID inexistente
        (p. ej. exportado desde otro Odoo) se trata como fila sin ID para que se
        busque el registro por su clave natural en lugar de duplicarlo."""
        xmlid = str(xmlid).strip()
        if '.' not in xmlid:
            xmlid = '__import__.%s' % xmlid
        try:
            registro = self.env.ref(xmlid, raise_if_not_found=False)
        except ValueError:
            return False
        return bool(registro) and registro._name == self._name

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

        if fields and '.id' not in fields:
            if 'id' in fields:
                id_idx = fields.index('id')
            else:
                fields.append('id')
                id_idx = len(fields) - 1
                for fila in data:
                    fila.append('')
            usados = set()
            for fila in data:
                if self._flota_import_tiene_valor(fila[id_idx]) and self._flota_import_xmlid_valido(fila[id_idx]):
                    continue
                valores = {f: v for f, v in zip(fields, fila) if '/' not in f}
                registro = self._flota_import_buscar_existente(valores)
                if registro and registro.id not in usados:
                    usados.add(registro.id)
                    fila[id_idx] = registro._flota_import_xmlid()

        return super().load(fields, data)
