from odoo import models, fields, api
from odoo.exceptions import ValidationError

class FlotaUbicacion(models.Model):
    _name = 'flota.ubicacion'
    _description = 'Ubicación de Flota'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'flota.nombre.mixin']
    _order = 'name asc'
    _flota_import_autocrear = True

    name = fields.Char(string='Nombre de la Ubicación', required=True, index=True, tracking=True)
    code = fields.Char(string='Código / Sigla', tracking=True)
    active = fields.Boolean(default=True, string='Activo', tracking=True)
    
    empleado_ids = fields.One2many(
        'flota.empleado', 
        'ubicacion_id', 
        string='Empleados'
    )
    total_empleados = fields.Integer(
        string='Total Empleados', 
        compute='_compute_empleados_counts', 
        store=True
    )
    empleados_activos_count = fields.Integer(
        string='Empleados Activos',
        compute='_compute_empleados_counts',
        store=True
    )
    empleados_inactivos_count = fields.Integer(
        string='Empleados Inactivos',
        compute='_compute_empleados_counts',
        store=True
    )
    tiene_inactivos = fields.Boolean(
        string='Tiene Inactivos',
        compute='_compute_empleados_counts',
        store=True
    )

    @api.constrains('name')
    def _check_name_unique(self):
        for record in self:
            if record.name:
                domain = [('nombre_busqueda', '=', record.nombre_busqueda), ('id', '!=', record.id)]
                if self.with_context(active_test=False).search_count(domain) > 0:
                    raise ValidationError('El nombre de la ubicación debe ser único.')

    @api.depends('empleado_ids', 'empleado_ids.estado', 'empleado_ids.active')
    def _compute_empleados_counts(self):
        for record in self:
            emps = record.empleado_ids
            record.total_empleados = len(emps)
            record.empleados_activos_count = len(emps.filtered(lambda e: e.estado == 'active'))
            record.empleados_inactivos_count = len(emps.filtered(lambda e: e.estado == 'inactive'))
            record.tiene_inactivos = record.empleados_inactivos_count > 0

    def action_view_empleados(self):
        self.ensure_one()
        return {
            'name': f'Empleados en {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'flota.empleado',
            'view_mode': 'list,kanban,form',
            'domain': [('ubicacion_id', '=', self.id)],
            'context': {'default_ubicacion_id': self.id, 'active_test': False}
        }
