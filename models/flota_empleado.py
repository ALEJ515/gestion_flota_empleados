import json
import logging
import requests
from odoo import models, fields, api
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

    # Campo Computado: Compañeros del Mismo Departamento
    companeros_departamento_ids = fields.One2many(
        'flota.empleado',
        compute='_compute_companeros_departamento',
        string='Compañeros de Departamento'
    )

    # Campos Integración n8n
    n8n_sync_status = fields.Selection([
        ('pending', 'Pendiente'),
        ('synced', 'Sincronizado'),
        ('error', 'Error')
    ], string='Estado Sync n8n', default='pending', readonly=True, copy=False, tracking=True)
    
    n8n_last_sync = fields.Datetime(string='Última Sincronización n8n', readonly=True, copy=False)
    n8n_response_log = fields.Text(string='Log de Respuesta n8n', readonly=True, copy=False)

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

    def prepare_n8n_payload(self):
        self.ensure_one()
        return {
            'event': 'empleado_flota_updated',
            'id': self.id,
            'nombre': self.name,
            'departamento': self.departamento_id.name if self.departamento_id else '',
            'ubicacion': self.ubicacion_id.name if self.ubicacion_id else '',
            'cargo': self.cargo or '',
            'numero_flota': self.numero_flota or '',
            'estado': self.estado,
            'active': self.active,
            'timestamp': fields.Datetime.now().isoformat()
        }

    def action_sync_n8n(self):
        """ Envía la información del empleado al Webhook configurado en n8n """
        ICP = self.env['ir.config_parameter'].sudo()
        webhook_url = ICP.get_param('gestion_flota_empleados.n8n_webhook_url')
        api_key = ICP.get_param('gestion_flota_empleados.n8n_api_key')

        if not webhook_url:
            raise UserError('No se ha configurado la URL del Webhook de n8n en los Ajustes del módulo.')

        headers = {
            'Content-Type': 'application/json',
        }
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        for record in self:
            payload = record.prepare_n8n_payload()
            try:
                response = requests.post(webhook_url, json=payload, headers=headers, timeout=10)
                if response.status_code in [200, 201, 202]:
                    record.write({
                        'n8n_sync_status': 'synced',
                        'n8n_last_sync': fields.Datetime.now(),
                        'n8n_response_log': f'HTTP {response.status_code}: {response.text[:500]}'
                    })
                else:
                    record.write({
                        'n8n_sync_status': 'error',
                        'n8n_last_sync': fields.Datetime.now(),
                        'n8n_response_log': f'HTTP {response.status_code}: {response.text[:500]}'
                    })
            except Exception as e:
                _logger.error("Error conectando con n8n: %s", str(e))
                record.write({
                    'n8n_sync_status': 'error',
                    'n8n_last_sync': fields.Datetime.now(),
                    'n8n_response_log': f'Error de Conexión: {str(e)}'
                })
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super(FlotaEmpleado, self).create(vals_list)
        ICP = self.env['ir.config_parameter'].sudo()
        auto_sync = ICP.get_param('gestion_flota_empleados.n8n_auto_sync')
        if auto_sync:
            records.action_sync_n8n()
        return records

    def write(self, vals):
        res = super(FlotaEmpleado, self).write(vals)
        ICP = self.env['ir.config_parameter'].sudo()
        auto_sync = ICP.get_param('gestion_flota_empleados.n8n_auto_sync')
        if auto_sync and not self.env.context.get('skip_n8n_sync'):
            self.action_sync_n8n()
        return res
