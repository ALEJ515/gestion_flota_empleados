from odoo import models, fields, api, _
from odoo.exceptions import UserError


class FlotaRutaMassUpdateWizard(models.TransientModel):
    _name = 'flota.ruta.mass.update.wizard'
    _description = 'Asistente de Asignación Masiva de Rutas'

    ruta_ids = fields.Many2many(
        'flota.ruta',
        string='Rutas Seleccionadas',
        default=lambda self: self.env.context.get('active_ids', [])
    )

    set_ubicacion = fields.Boolean(string='Modificar Localidad / Ubicación (CEDI)')
    ubicacion_id = fields.Many2one('flota.ubicacion', string='Localidad / Ubicación', ondelete='set null')

    set_tipo = fields.Boolean(string='Modificar Tipo de Ruta')
    tipo = fields.Selection([
        ('vendedor', 'Vendedor'),
        ('distribuidor', 'Distribuidor'),
        ('otro', 'Otro'),
    ], string='Tipo de Ruta')

    set_active = fields.Boolean(string='Modificar Estado (Activo/Archivado)')
    active = fields.Boolean(string='Activo', default=True)

    count_rutas = fields.Integer(compute='_compute_count_rutas', string='Cantidad de Rutas')

    @api.depends('ruta_ids')
    def _compute_count_rutas(self):
        for record in self:
            record.count_rutas = len(record.ruta_ids)

    def action_apply_mass_update(self):
        self.ensure_one()
        if not self.ruta_ids:
            raise UserError(_('No hay rutas seleccionadas para actualizar.'))

        vals = {}
        changes_desc = []

        if self.set_ubicacion:
            vals['ubicacion_id'] = self.ubicacion_id.id or False
            changes_desc.append(f"Localidad/Ubicación: {self.ubicacion_id.name or 'Sin asignar'}")

        if self.set_tipo:
            if not self.tipo:
                raise UserError(_('Por favor seleccione un Tipo de Ruta válido.'))
            vals['tipo'] = self.tipo
            tipo_str = dict(self._fields['tipo'].selection).get(self.tipo)
            changes_desc.append(f"Tipo de Ruta: {tipo_str}")

        if self.set_active:
            vals['active'] = self.active
            changes_desc.append(f"Estado: {'Activo' if self.active else 'Archivado'}")

        if not vals:
            raise UserError(_('Por favor active al menos una casilla de verificación para aplicar cambios masivos.'))

        self.ruta_ids.write(vals)

        note = _("<b>Asignación Masiva Aplicada:</b><br/>") + "<br/>".join(changes_desc)
        for ruta in self.ruta_ids:
            ruta.message_post(body=note)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Asignación Masiva Exitosa'),
                'message': _('Se han actualizado %s rutas correctamente.') % len(self.ruta_ids),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
