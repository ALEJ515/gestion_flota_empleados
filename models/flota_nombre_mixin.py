from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .nombre_utils import clave_nombre, normalizar_nombre


class FlotaNombreMixin(models.AbstractModel):
    _name = 'flota.nombre.mixin'
    _inherit = 'flota.import.mixin'
    _description = 'Nombres normalizados de empleados y estructura'

    nombre_busqueda = fields.Char(
        string='Nombre Normalizado (Interno)',
        compute='_compute_nombre_busqueda', store=True, index=True,
    )

    @api.depends('name')
    def _compute_nombre_busqueda(self):
        for rec in self:
            rec.nombre_busqueda = clave_nombre(rec.name)

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([
            dict(vals, name=normalizar_nombre(vals['name'])) if 'name' in vals else dict(vals)
            for vals in vals_list
        ])

    def write(self, vals):
        vals = dict(vals)
        if 'name' in vals:
            vals['name'] = normalizar_nombre(vals['name'])
        return super().write(vals)

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        # Odoo resuelve las referencias de importación con name_search(operator='=').
        if name and operator == '=':
            matches = self.search(
                [('nombre_busqueda', '=', clave_nombre(name))] + list(domain or []),
                limit=0 if not limit else max(limit, 2),
            )
            if len(matches) > 1:
                raise ValidationError(_(
                    'El nombre "%s" corresponde a varios registros. Importe la referencia '
                    'por ID externo para identificarla sin ambigüedad.'
                ) % name)
            return [(rec.id, rec.display_name) for rec in matches]
        return super().name_search(name=name, domain=domain, operator=operator, limit=limit)

    @api.model
    def _flota_import_buscar_existente(self, fila):
        nombre = fila.get('name')
        if isinstance(nombre, str) and nombre.strip():
            matches = self.with_context(active_test=False).search(
                [('nombre_busqueda', '=', clave_nombre(nombre))], limit=2,
            )
            if len(matches) > 1:
                raise ValidationError(_(
                    'Hay varios registros con el nombre "%s". Conserve la columna ID '
                    'para actualizar el registro correcto.'
                ) % nombre)
            return matches
        return self.browse()
