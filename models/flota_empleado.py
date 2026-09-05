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
    penultima_facturacion_monto = fields.Monetary(
        string='Penúltima Facturación (RD$)',
        currency_field='currency_id',
        readonly=True,
        tracking=True
    )
    ultima_facturacion_periodo = fields.Char(
        string='Periodo Última Factura',
        readonly=True,
        tracking=True
    )
    comparativa_facturacion = fields.Selection([
        ('subio', 'Aumentó (▲)'),
        ('bramo', 'Disminuyó (▼)'),
        ('igual', 'Igual (=)'),
        ('nuevo', 'Nuevo')
    ], compute='_compute_comparativa_facturacion', string='Tendencia Consumo', store=True)

    comparativa_indicador_html = fields.Html(
        compute='_compute_comparativa_facturacion',
        string='Tendencia Visual',
        store=True
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

    @api.depends('ultima_facturacion_monto', 'penultima_facturacion_monto')
    def _compute_comparativa_facturacion(self):
        for rec in self:
            if not rec.penultima_facturacion_monto and not rec.ultima_facturacion_monto:
                rec.comparativa_facturacion = 'nuevo'
                rec.comparativa_indicador_html = '<span class="badge bg-secondary">Sin historial</span>'
            elif not rec.penultima_facturacion_monto or rec.penultima_facturacion_monto == 0:
                rec.comparativa_facturacion = 'subio'
                rec.comparativa_indicador_html = f'<span class="badge bg-info" title="Nuevo cargo o registro inicial">▲ RD${rec.ultima_facturacion_monto:,.2f}</span>'
            elif rec.ultima_facturacion_monto > rec.penultima_facturacion_monto:
                dif = rec.ultima_facturacion_monto - rec.penultima_facturacion_monto
                rec.comparativa_facturacion = 'subio'
                rec.comparativa_indicador_html = f'<span class="badge bg-warning text-dark" title="Consumo mayor que el anterior (+RD${dif:,.2f})">▲ +RD${dif:,.2f}</span>'
            elif rec.ultima_facturacion_monto < rec.penultima_facturacion_monto:
                dif = rec.penultima_facturacion_monto - rec.ultima_facturacion_monto
                rec.comparativa_facturacion = 'bramo'
                rec.comparativa_indicador_html = f'<span class="badge bg-success" title="Consumo menor que el anterior (-RD${dif:,.2f})">▼ -RD${dif:,.2f}</span>'
            else:
                rec.comparativa_facturacion = 'igual'
                rec.comparativa_indicador_html = '<span class="badge bg-light text-dark border">= Sin variación</span>'

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

    @api.constrains('numero_flota', 'name')
    def _check_unique_fields(self):
        if self.env.context.get('install_mode'):
            return
        for record in self:
            if record.numero_flota:
                domain_phone = [('numero_flota', '=', record.numero_flota.strip()), ('id', '!=', record.id)]
                if self.with_context(active_test=False).search_count(domain_phone) > 0:
                    raise ValidationError(_('El número de flota (%s) ya pertenece a otro empleado registrado.') % record.numero_flota)
            if record.name:
                domain_name = [('name', '=ilike', record.name.strip()), ('id', '!=', record.id)]
                if self.with_context(active_test=False).search_count(domain_name) > 0:
                    raise ValidationError(_('El nombre completo (%s) ya está registrado en el sistema.') % record.name)
