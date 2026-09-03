from odoo import fields, models
from odoo.exceptions import UserError

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    n8n_webhook_url = fields.Char(
        string='Webhook URL n8n',
        config_parameter='gestion_flota_empleados.n8n_webhook_url',
        help='URL del endpoint de recepción en n8n (ej: https://n8n.domain.com/webhook/flota)'
    )
    n8n_api_key = fields.Char(
        string='Token / API Key n8n',
        config_parameter='gestion_flota_empleados.n8n_api_key',
        help='Token Bearer opcional para autenticar las peticiones hacia n8n'
    )
    n8n_auto_sync = fields.Boolean(
        string='Sincronización Automática',
        config_parameter='gestion_flota_empleados.n8n_auto_sync',
        help='Enviar datos a n8n de forma automática al crear o modificar un empleado'
    )

    def action_force_n8n_sync_all(self):
        """ Ejecuta la sincronización masiva de todos los empleados hacia el webhook de n8n """
        empleados = self.env['flota.empleado'].sudo().search([('active', '=', True)])
        if not empleados:
            raise UserError('No existen empleados activos registrados para sincronizar.')
        empleados.action_sync_n8n()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Sincronización n8n Ejecutada',
                'message': f'Se ha procesado el envío masivo para {len(empleados)} registros de empleados.',
                'type': 'success',
                'sticky': False,
            }
        }
