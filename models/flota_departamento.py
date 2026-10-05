from odoo import models, fields, api
from odoo.exceptions import ValidationError

class FlotaDepartamento(models.Model):
    _name = 'flota.departamento'
    _description = 'Departamento de Flota'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'flota.nombre.mixin']
    _order = 'name asc'

    name = fields.Char(string='Nombre del Departamento', required=True, index=True, tracking=True)
    code = fields.Char(string='Código Interno', tracking=True)
    active = fields.Boolean(default=True, string='Activo', tracking=True)
    ubicacion_id = fields.Many2one(
        'flota.ubicacion',
        string='Ubicación / CEDI',
        tracking=True,
        help="Ubicación o CEDI al que pertenece este departamento. Se usa para agrupar el Consolidado por Departamento en las conciliaciones de factura."
    )
    
    ultima_facturacion_monto = fields.Monetary(
        string='Última Facturación Depto (RD$)',
        currency_field='currency_id',
        readonly=True
    )
    ultima_facturacion_periodo = fields.Char(
        string='Periodo Última Factura',
        readonly=True
    )
    penultima_facturacion_monto = fields.Monetary(
        string='Penúltima Facturación Depto (RD$)',
        currency_field='currency_id',
        readonly=True
    )
    penultima_facturacion_periodo = fields.Char(
        string='Periodo Penúltima Factura',
        readonly=True
    )
    currency_id = fields.Many2one('res.currency', string='Moneda', default=lambda self: self.env.company.currency_id)
    
    empleado_ids = fields.One2many(
        'flota.empleado', 
        'departamento_id', 
        string='Empleados'
    )
    subdepartamento_ids = fields.One2many(
        'flota.subdepartamento', 'departamento_id', string='Subdepartamentos'
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
