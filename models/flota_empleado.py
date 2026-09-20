import logging
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from .phone_utils import whatsapp_url

_logger = logging.getLogger(__name__)

def _normalize_phone(phone_str):
    if not phone_str:
        return ''
    digits = re.sub(r'\D', '', str(phone_str))
    if len(digits) > 10 and digits.startswith('1'):
        digits = digits[-10:]
    return digits

def _formatear_numero_flota(valor):
    """Reformatea el número de flota a un único formato consistente 'XXX XXX-XXXX' cuando se
    detectan 10 dígitos (formato dominicano estándar), para que todos los números queden
    registrados de la misma manera y las búsquedas/exportes no fallen por diferencias de
    espacios o guiones. Si no son exactamente 10 dígitos (ej. extensiones u otros formatos),
    se deja el valor tal como fue ingresado."""
    if not valor:
        return valor
    digitos = _normalize_phone(valor)
    if len(digitos) == 10:
        return f"{digitos[0:3]} {digitos[3:6]}-{digitos[6:10]}"
    return valor

class FlotaEmpleado(models.Model):
    _name = 'flota.empleado'
    _description = 'Empleado y Flota Telefónica'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc, id desc'

    def _auto_init(self):
        self.env.cr.execute("""
            ALTER TABLE flota_empleado 
            ADD COLUMN IF NOT EXISTS penultima_facturacion_periodo VARCHAR;
        """)
        return super()._auto_init()

    name = fields.Char(string='Nombre Completo', required=True, index=True, tracking=True)
    departamento_id = fields.Many2one(
        'flota.departamento', 
        string='Departamento', 
        required=False,
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
    ruta_id = fields.Many2one(
        'flota.ruta',
        string='Ruta',
        ondelete='restrict',
        index=True,
        tracking=True,
        help="Ruta asignada al empleado. Ej. NTP0103 (vendedor) o DIST+10 (distribuidor)."
    )
    cargo = fields.Char(string='Cargo', required=True, tracking=True)
    numero_flota = fields.Char(string='Número Flota', required=True, index=True, tracking=True)
    numero_flota_digits = fields.Char(
        string='Número Flota (Normalizado)',
        compute='_compute_numero_flota_digits',
        store=True,
        index=True,
        help="Campo interno de solo lectura: contiene únicamente los dígitos del Número Flota (sin espacios, "
             "guiones ni paréntesis). Se usa para que la búsqueda encuentre el número sin importar cómo se "
             "haya escrito (con o sin espacios/guiones)."
    )
    estado = fields.Selection([
        ('draft', 'Borrador'),
        ('active', 'Activo'),
        ('inactive', 'Inactivo')
    ], string='Estado', default='active', required=True, index=True, tracking=True)
    
    notas = fields.Text(string='Notas')
    active = fields.Boolean(default=True, string='Activo en Sistema', tracking=True)
    en_ultima_factura = fields.Boolean(string='Presente en Última Factura Claro', default=True, tracking=True, help="Indica si el número de flota de este empleado fue detectado en la última factura de Claro.")
    es_nuevo_auto = fields.Boolean(string='Creado Automáticamente por Claro', default=False, tracking=True, help="Indica si el empleado fue registrado automáticamente desde una factura de Claro.")

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
    penultima_facturacion_periodo = fields.Char(
        string='Periodo Penúltima Factura',
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

    entrega_equipo_ids = fields.One2many(
        'flota.entrega.equipo',
        'empleado_id',
        string='Actas de Entrega de Equipos'
    )
    entrega_equipo_count = fields.Integer(
        string='Total Actas de Equipos',
        compute='_compute_entrega_equipo_count'
    )

    @api.depends('entrega_equipo_ids')
    def _compute_entrega_equipo_count(self):
        for rec in self:
            rec.entrega_equipo_count = len(rec.entrega_equipo_ids)

    def action_view_entregas_equipo(self):
        self.ensure_one()
        return {
            'name': f'Actas de Entrega de Equipos - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'flota.entrega.equipo',
            'view_mode': 'list,form',
            'domain': [('empleado_id', '=', self.id)],
            'context': {'default_empleado_id': self.id}
        }

    # Campo Computado: Compañeros del Mismo Departamento
    companeros_departamento_ids = fields.One2many(
        'flota.empleado',
        compute='_compute_companeros_departamento',
        string='Compañeros de Departamento'
    )

    def _update_facturacion_stats(self):
        """ Actualiza los montos y periodos de la última y penúltima facturación basándose en su historial """
        for rec in self:
            lines = rec.historial_factura_linea_ids.sorted(
                key=lambda l: (
                    l.conciliacion_id.fecha_factura or fields.Date.today(),
                    l.conciliacion_id.id or 0,
                    l.id or 0
                ),
                reverse=True
            )
            periodos_seen = []
            distinct_lines = []
            for line in lines:
                p = line.conciliacion_id.periodo or line.periodo or f"conc_{line.conciliacion_id.id}"
                if p not in periodos_seen:
                    periodos_seen.append(p)
                    distinct_lines.append(line)

            if distinct_lines:
                latest = distinct_lines[0]
                vals = {
                    'ultima_facturacion_monto': latest.total_linea,
                    'ultima_facturacion_periodo': str(latest.periodo or latest.conciliacion_id.periodo or ''),
                }
                if len(distinct_lines) > 1:
                    prev = distinct_lines[1]
                    vals['penultima_facturacion_monto'] = prev.total_linea
                    vals['penultima_facturacion_periodo'] = str(prev.periodo or prev.conciliacion_id.periodo or '')
                else:
                    vals['penultima_facturacion_monto'] = 0.0
                    vals['penultima_facturacion_periodo'] = ''
                rec.write(vals)

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

    @api.depends('numero_flota')
    def _compute_numero_flota_digits(self):
        for record in self:
            record.numero_flota_digits = _normalize_phone(record.numero_flota)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('numero_flota'):
                vals['numero_flota'] = _formatear_numero_flota(vals['numero_flota'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('numero_flota'):
            vals['numero_flota'] = _formatear_numero_flota(vals['numero_flota'])
        return super().write(vals)

    def action_open_whatsapp(self):
        self.ensure_one()
        url = whatsapp_url(self.numero_flota)
        if not url:
            raise UserError(_('El empleado no tiene un número válido para abrir WhatsApp.'))
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    @api.constrains('numero_flota', 'name')
    def _check_unique_fields(self):
        if self.env.context.get('install_mode'):
            return
        for record in self:
            if record.numero_flota:
                norm = _normalize_phone(record.numero_flota)
                if norm:
                    # Se acota la búsqueda por los últimos dígitos (ilike, usa índice)
                    # en vez de traer TODOS los empleados a Python en cada guardado:
                    # con cientos de registros esa comparación uno a uno podía sentirse
                    # como que la página se queda "cargando" al crear/editar un empleado.
                    filtro_digitos = norm[-7:] if len(norm) >= 7 else norm
                    candidatos = self.with_context(active_test=False).search([
                        ('id', '!=', record.id),
                        ('numero_flota_digits', 'ilike', filtro_digitos),
                    ])
                    for ot in candidatos:
                        if ot.numero_flota_digits == norm:
                            raise ValidationError(_('El número de flota (%s) ya pertenece al empleado %s.') % (record.numero_flota, ot.name))
            if record.name:
                clean_n = record.name.strip()
                domain_name = [('name', '=ilike', clean_n), ('id', '!=', record.id)]
                if self.with_context(active_test=False).search_count(domain_name) > 0:
                    raise ValidationError(_('El nombre completo (%s) ya está registrado en el sistema.') % record.name)
