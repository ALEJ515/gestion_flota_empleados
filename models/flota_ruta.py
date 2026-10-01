from odoo import models, fields, api
from odoo.exceptions import ValidationError

class FlotaRuta(models.Model):
    _name = 'flota.ruta'
    _description = 'Ruta de Empleado (Vendedor / Distribuidor)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'

    name = fields.Char(
        string='Código de Ruta',
        required=True,
        index=True,
        tracking=True,
        help="Código de la ruta asignada al empleado. Ej. NTP0103 (vendedor) o DIST+10 (distribuidor, donde 10 es el número de almacén)."
    )
    tipo = fields.Selection([
        ('vendedor', 'Vendedor'),
        ('distribuidor', 'Distribuidor'),
        ('otro', 'Otro'),
    ], string='Tipo de Ruta', default='vendedor', tracking=True)
    descripcion = fields.Char(string='Descripción', tracking=True, help="Detalle adicional de la ruta, ej. nombre de la zona o almacén.")
    ubicacion_id = fields.Many2one(
        'flota.ubicacion', string='Localidad / Ubicación (CEDI)', tracking=True, ondelete='set null',
        help="CEDI o localidad a la que pertenece esta ruta. Sirve para poder filtrar/agrupar rutas y empleados por zona."
    )
    active = fields.Boolean(default=True, string='Activo', tracking=True)

    empleado_ids = fields.One2many(
        'flota.empleado',
        'ruta_id',
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
                    raise ValidationError('El código de ruta debe ser único.')

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
            'name': f'Empleados en Ruta {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'flota.empleado',
            'view_mode': 'list,kanban,form',
            'domain': [('ruta_id', '=', self.id)],
            'context': {'default_ruta_id': self.id, 'active_test': False}
        }
