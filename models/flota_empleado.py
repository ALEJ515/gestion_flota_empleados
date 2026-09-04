import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class FlotaEmpleado(models.Model):
    _name = 'flota.empleado'
    _description = 'Empleado y Flota Telefónica'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc, id desc'

    name = fields.Char(string='Nombre Completo', required=True, index=True, tracking=True)
    departamento_id = fields.Many2one(
        'flota.departamento', 
        string='Departamento', 
        required=True, 
        ondelete='restrict',
        index=True,
        tracking=True
    )
    ubicacion_id = fields.Many2one(
        'flota.ubicacion', 
        string='Ubicación', 
        ondelete='restrict',
        index=True,
        tracking=True
    )
    cargo = fields.Char(string='Cargo', required=True, tracking=True)
    numero_flota = fields.Char(string='Número Flota', required=True, index=True, tracking=True)
    estado = fields.Selection([
        ('draft', 'Borrador'),
        ('active', 'Activo'),
        ('inactive', 'Inactivo')
    ], string='Estado', default='active', required=True, index=True, tracking=True)
    
    notas = fields.Text(string='Notas')
    active = fields.Boolean(default=True, string='Activo en Sistema', tracking=True)

    # Campos de Facturación y Consumos Telefónicos
    ultima_facturacion_monto = fields.Monetary(
        string='Última Facturación (RD$)',
        currency_field='currency_id',
        readonly=True,
        tracking=True
    )
    ultima_facturacion_periodo = fields.Char(
        string='Periodo Última Factura',
        readonly=True,
        tracking=True
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        default=lambda self: self.env.company.currency_id
    )

    historial_factura_linea_ids = fields.One2many(
        'flota.factura.linea',
        'empleado_id',
        string='Historial de Facturación y Consumos'
    )

    # Campo Computado: Compañeros del Mismo Departamento
    companeros_departamento_ids = fields.One2many(
        'flota.empleado',
        compute='_compute_companeros_departamento',
        string='Compañeros de Departamento'
    )

    @api.depends('departamento_id')
    def _compute_companeros_departamento(self):
        for record in self:
            if record.departamento_id and record.id:
                record.companeros_departamento_ids = self.search([
                    ('departamento_id', '=', record.departamento_id.id),
                    ('id', '!=', record.id)
                ])
            else:
                record.companeros_departamento_ids = self.browse()

    @api.constrains('numero_flota')
    def _check_numero_flota_unique(self):
        for record in self:
            if record.numero_flota:
                domain = [('numero_flota', '=', record.numero_flota), ('id', '!=', record.id)]
                if self.search_count(domain) > 0:
                    raise ValidationError('El número de flota debe ser único por empleado.')
