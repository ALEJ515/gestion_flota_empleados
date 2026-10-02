import logging

from odoo import api, SUPERUSER_ID


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    actas = env['flota.entrega.equipo'].search([])
    for name in ('cargo', 'ruta_id', 'ubicacion_id', 'recibido_por', 'telefono_flota'):
        env.add_to_compute(actas._fields[name], actas)
    env.flush_all()
    _logger.info("Sincronizados los datos del empleado en %s actas existentes.", len(actas))
