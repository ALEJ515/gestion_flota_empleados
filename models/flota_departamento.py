from odoo import models, fields, api
from odoo.exceptions import ValidationError

class FlotaDepartamento(models.Model):
    _name = 'flota.departamento'
    _description = 'Departamento de Flota'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'

    name = fields.Char(string='Nombre del Departamento', required=True, index=True, tracking=True)
    code = fields.Char(string='Código Interno', tracking=True)
    active = fields.Boolean(default=True, string='Activo', tracking=True)
    
    empleado_ids = fields.One2many(
        'flota.empleado', 
        'departamento_id', 
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
                domain = [('name', '=ilike', record.name), ('id', '!=', record.id)]
                if self.search_count(domain) > 0:
                    raise ValidationError('El nombre del departamento debe ser único.')

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
            'domain': [('departamento_id', '=', self.id)],
            'context': {'default_departamento_id': self.id, 'active_test': False}
        }
