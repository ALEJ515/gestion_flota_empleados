from odoo import models, fields, api


class FlotaPlanDatos(models.Model):
    _name = 'flota.plan.datos'
    _description = 'Plan de Datos y Telefonía'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'flota.import.mixin']
    _order = 'name asc'
    _flota_import_autocrear = True

    name = fields.Char(
        string='Nombre del Plan',
        required=True,
        index=True,
        tracking=True,
        help="Nombre comercial o identificador del plan. Ej. Plan Flota 10GB, Plan Ilimitado Voz y Data."
    )
    codigo = fields.Char(
        string='Código / Referencia',
        tracking=True,
        help="Código interno o código provisto por la telefónica (ej. CL-CORP-10)."
    )
    operador = fields.Selection([
        ('claro', 'Claro'),
        ('altice', 'Altice'),
        ('viva', 'Viva'),
        ('otro', 'Otro'),
    ], string='Operador / Proveedor', default='claro', required=True, tracking=True)

    capacidad_datos = fields.Char(
        string='Capacidad de Data',
        tracking=True,
        help="Ej. 5 GB, 10 GB, 20 GB, Ilimitado, etc."
    )
    minutos = fields.Char(
        string='Minutos de Voz',
        tracking=True,
        help="Ej. Ilimitado cerrado, 500 Minutos a todas las redes, etc."
    )
    costo_mensual = fields.Monetary(
        string='Tarifa Mensual (RD$)',
        currency_field='currency_id',
        tracking=True,
        help="Costo o renta mensual base del plan sin impuestos o con impuestos según corresponda."
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        default=lambda self: self.env.company.currency_id
    )
    descripcion = fields.Text(string='Detalle / Condiciones del Plan')
    active = fields.Boolean(default=True, string='Activo', tracking=True)

    empleado_ids = fields.One2many(
        'flota.empleado',
        'plan_datos_id',
        string='Empleados Asignados'
    )
    total_empleados = fields.Integer(
        string='Total Empleados',
        compute='_compute_total_empleados',
        store=True
    )

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Ya existe un plan de datos con este nombre.'),
    ]

    @api.depends('empleado_ids')
    def _compute_total_empleados(self):
        for rec in self:
            rec.total_empleados = len(rec.empleado_ids)

    def action_view_empleados(self):
        self.ensure_one()
        return {
            'name': f'Empleados con {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'flota.empleado',
            'view_mode': 'list,kanban,form',
            'domain': [('plan_datos_id', '=', self.id)],
            'context': {'default_plan_datos_id': self.id, 'active_test': False}
        }
