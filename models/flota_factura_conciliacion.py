import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class FlotaFacturaConciliacion(models.Model):
    _name = 'flota.factura.conciliacion'
    _description = 'Conciliación Financiera de Factura de Flota'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'periodo desc, id desc'

    name = fields.Char(string='Referencia / Folio', required=True, copy=False, default=lambda self: _('Nuevo'), index=True, tracking=True)
    proveedor = fields.Char(string='Proveedor Telecom', default='Claro Dominicana', required=True, tracking=True)
    periodo = fields.Char(string='Periodo / Mes (AAAA-MM)', required=True, index=True, tracking=True)
    fecha_factura = fields.Date(string='Fecha de Factura', default=fields.Date.context_today, required=True, tracking=True)
    
    # --- DATOS GENERALES FACTURA CLARO ---
    renta_mensual = fields.Monetary(string='Renta Mensual', currency_field='currency_id', default=0.0, tracking=True)
    renta_otros_servicios = fields.Monetary(string='Renta Otros Servicios', currency_field='currency_id', default=0.0, tracking=True)
    uso_data_movil = fields.Monetary(string='Uso Data Móvil', currency_field='currency_id', default=0.0, tracking=True)
    llamadas_roaming = fields.Monetary(string='Llamadas Roaming', currency_field='currency_id', default=0.0, tracking=True)
    otros_cargos_creditos = fields.Monetary(string='Otros Cargos / Créditos (CR)', currency_field='currency_id', default=0.0, tracking=True, help="Monto de descuentos o notas de crédito (monto negativo o positivo ajustado)")

    # --- DATOS COMPUTADOS AUTOMÁTICAMENTE ---
    subtotal = fields.Monetary(string='Subtotal Factura', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)
    itbis_monto = fields.Monetary(string='ITBIS (18%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)
    cdt_monto = fields.Monetary(string='CDT (2%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)
    isc_monto = fields.Monetary(string='ISC (10%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)
    total_mes = fields.Monetary(string='Total del Mes', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)

    currency_id = fields.Many2one('res.currency', string='Moneda', default=lambda self: self.env.company.currency_id)
    estado = fields.Selection([
        ('draft', 'Borrador'),
        ('procesando', 'Procesando n8n'),
        ('conciliado', 'Conciliado'),
        ('error', 'Con Errores / Desviaciones')
    ], string='Estado', default='draft', required=True, index=True, tracking=True)

    notes = fields.Text(string='Observaciones y Notas')

    # Relaciones
    linea_ids = fields.One2many('flota.factura.linea', 'conciliacion_id', string='Desglose por Empleado / Número')
    resumen_depto_ids = fields.One2many('flota.factura.departamento.resumen', 'conciliacion_id', string='Resumen por Departamento')

    # KPIs Computados
    count_lineas = fields.Integer(string='Total Líneas', compute='_compute_kpis', store=True)
    count_excesos = fields.Integer(string='Líneas con Exceso', compute='_compute_kpis', store=True)
    monto_excesos = fields.Monetary(string='Monto Total Excesos', compute='_compute_kpis', store=True, currency_field='currency_id')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('flota.factura.conciliacion') or _('FAC-CLARO-%s') % fields.Date.today()
        return super(FlotaFacturaConciliacion, self).create(vals_list)

    @api.depends('renta_mensual', 'renta_otros_servicios', 'uso_data_movil', 'llamadas_roaming', 'otros_cargos_creditos')
    def _compute_totales_factura(self):
        for rec in self:
            sub = rec.renta_mensual + rec.renta_otros_servicios + rec.uso_data_movil + rec.llamadas_roaming + rec.otros_cargos_creditos
            rec.subtotal = sub
            rec.itbis_monto = sub * 0.18
            rec.cdt_monto = sub * 0.02
            rec.isc_monto = sub * 0.10
            rec.total_mes = sub + rec.itbis_monto + rec.cdt_monto + rec.isc_monto

    @api.depends('linea_ids', 'linea_ids.estado_linea', 'linea_ids.monto_uso_adicional', 'linea_ids.monto_roaming')
    def _compute_kpis(self):
        for rec in self:
            rec.count_lineas = len(rec.linea_ids)
            excesos = rec.linea_ids.filtered(lambda l: l.estado_linea in ['exceso_data', 'exceso_roaming'])
            rec.count_excesos = len(excesos)
            rec.monto_excesos = sum(excesos.mapped(lambda l: l.monto_uso_adicional + l.monto_roaming))

    def action_generar_resumen_departamentos(self):
        """ Agrupa y consolida el gasto por Departamento / CEDI """
        for rec in self:
            rec.resumen_depto_ids.unlink()
            dept_totals = {}
            for linea in rec.linea_ids:
                dept_id = linea.departamento_id.id if linea.departamento_id else 0
                dept_name = linea.departamento_id.name if linea.departamento_id else 'Sin Departamento'
                ubic_name = linea.ubicacion_id.name if linea.ubicacion_id else 'N/A'
                
                if dept_id not in dept_totals:
                    dept_totals[dept_id] = {
                        'departamento_id': linea.departamento_id.id if linea.departamento_id else False,
                        'ubicacion_id': linea.ubicacion_id.id if linea.ubicacion_id else False,
                        'cantidad_empleados': 0,
                        'monto_subtotal': 0.0,
                        'monto_total': 0.0
                    }
                dept_totals[dept_id]['cantidad_empleados'] += 1
                dept_totals[dept_id]['monto_subtotal'] += linea.subtotal_linea
                dept_totals[dept_id]['monto_total'] += linea.total_linea

            resumen_vals = []
            tot_gral = rec.total_mes if rec.total_mes else 1.0
            for d_id, data in dept_totals.items():
                pct = (data['monto_total'] / tot_gral) * 100.0
                resumen_vals.append((0, 0, {
                    'conciliacion_id': rec.id,
                    'departamento_id': data['departamento_id'],
                    'ubicacion_id': data['ubicacion_id'],
                    'cantidad_empleados': data['cantidad_empleados'],
                    'monto_subtotal': data['monto_subtotal'],
                    'monto_total': data['monto_total'],
                    'porcentaje_gasto': pct
                }))
            rec.write({'resumen_depto_ids': resumen_vals})

    def action_marcar_conciliado(self):
        self.ensure_one()
        self.action_generar_resumen_departamentos()
        self.write({'estado': 'conciliado'})
        self.message_post(body=_("Factura de Flota marcada como <b>Conciliada</b> correctamente."))

class FlotaFacturaLinea(models.Model):
    _name = 'flota.factura.linea'
    _description = 'Detalle de Factura por Línea / Empleado'
    _order = 'total_linea desc, id asc'

    conciliacion_id = fields.Many2one('flota.factura.conciliacion', string='Factura Conciliación', ondelete='cascade', index=True)
    numero_flota = fields.Char(string='Número Flota', required=True, index=True)
    
    empleado_id = fields.Many2one('flota.empleado', string='Empleado', ondelete='set null', index=True)
    departamento_id = fields.Many2one('flota.departamento', string='Departamento', related='empleado_id.departamento_id', store=True, readonly=True)
    ubicacion_id = fields.Many2one('flota.ubicacion', string='CEDI / Ubicación', related='empleado_id.ubicacion_id', store=True, readonly=True)
    cargo = fields.Char(string='Cargo', related='empleado_id.cargo', readonly=True)

    monto_renta_plan = fields.Monetary(string='Renta Plan', currency_field='currency_id', default=0.0)
    monto_otros_servicios = fields.Monetary(string='Otros Servicios', currency_field='currency_id', default=0.0)
    monto_uso_adicional = fields.Monetary(string='Uso Data/Voz Adicional', currency_field='currency_id', default=0.0)
    monto_roaming = fields.Monetary(string='Roaming / LD', currency_field='currency_id', default=0.0)
    monto_financiamiento = fields.Monetary(string='Financiamiento Equipo', currency_field='currency_id', default=0.0)
    monto_creditos = fields.Monetary(string='Créditos / Ajustes', currency_field='currency_id', default=0.0)

    subtotal_linea = fields.Monetary(string='Subtotal Línea', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    itbis_linea = fields.Monetary(string='ITBIS (18%)', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    cdt_linea = fields.Monetary(string='CDT (2%)', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    isc_linea = fields.Monetary(string='ISC (10%)', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    total_linea = fields.Monetary(string='Total Línea (RD$)', compute='_compute_linea_totals', store=True, currency_field='currency_id')

    currency_id = fields.Many2one('res.currency', string='Moneda', related='conciliacion_id.currency_id', store=True)

    estado_linea = fields.Selection([
        ('ok', 'Normal'),
        ('exceso_data', 'Exceso Data'),
        ('exceso_roaming', 'Exceso Roaming'),
        ('desconocido', 'Número No Registrado')
    ], string='Estado Línea', compute='_compute_estado_linea', store=True, default='ok')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Auto-link employee by numero_flota if not set
            if not vals.get('empleado_id') and vals.get('numero_flota'):
                num_clean = vals['numero_flota'].replace('-', '').replace(' ', '').replace('+', '')
                # Find matching employee
                emp = self.env['flota.empleado'].search([
                    '|',
                    ('numero_flota', '=', vals['numero_flota']),
                    ('numero_flota', '=', num_clean)
                ], limit=1)
                if emp:
                    vals['empleado_id'] = emp.id
        return super(FlotaFacturaLinea, self).create(vals_list)

    @api.depends('monto_renta_plan', 'monto_otros_servicios', 'monto_uso_adicional', 'monto_roaming', 'monto_financiamiento', 'monto_creditos')
    def _compute_linea_totals(self):
        for rec in self:
            sub = rec.monto_renta_plan + rec.monto_otros_servicios + rec.monto_uso_adicional + rec.monto_roaming + rec.monto_financiamiento + rec.monto_creditos
            rec.subtotal_linea = sub
            rec.itbis_linea = sub * 0.18
            rec.cdt_linea = sub * 0.02
            rec.isc_linea = sub * 0.10
            rec.total_linea = sub + rec.itbis_linea + rec.cdt_linea + rec.isc_linea

    @api.depends('empleado_id', 'monto_uso_adicional', 'monto_roaming')
    def _compute_estado_linea(self):
        for rec in self:
            if not rec.empleado_id:
                rec.estado_linea = 'desconocido'
            elif rec.monto_roaming > 0:
                rec.estado_linea = 'exceso_roaming'
            elif rec.monto_uso_adicional > 0:
                rec.estado_linea = 'exceso_data'
            else:
                rec.estado_linea = 'ok'


class FlotaFacturaDepartamentoResumen(models.Model):
    _name = 'flota.factura.departamento.resumen'
    _description = 'Resumen Consolidado de Factura por Departamento'
    _order = 'monto_total desc'

    conciliacion_id = fields.Many2one('flota.factura.conciliacion', string='Factura Conciliación', ondelete='cascade', index=True)
    departamento_id = fields.Many2one('flota.departamento', string='Departamento')
    ubicacion_id = fields.Many2one('flota.ubicacion', string='CEDI / Ubicación')
    cantidad_empleados = fields.Integer(string='Empleados')
    monto_subtotal = fields.Monetary(string='Subtotal Depto', currency_field='currency_id')
    monto_total = fields.Monetary(string='Total Depto (RD$)', currency_field='currency_id')
    porcentaje_gasto = fields.Float(string='% del Total General', digits=(5, 2))
    currency_id = fields.Many2one('res.currency', string='Moneda', related='conciliacion_id.currency_id')
