from odoo import models, fields, api, _
from odoo.exceptions import UserError


class FlotaEntregaEquipoReasignarWizard(models.TransientModel):
    _name = 'flota.entrega.equipo.reasignar.wizard'
    _description = 'Asistente para Reasignar Equipos de un Acta a Otro Empleado'

    entrega_id = fields.Many2one(
        'flota.entrega.equipo', string='Acta de Origen', required=True, readonly=True,
        default=lambda self: self.env.context.get('default_entrega_id')
    )
    empleado_actual_id = fields.Many2one(
        'flota.empleado', string='Empleado Actual de la Acta', related='entrega_id.empleado_id', readonly=True
    )
    nuevo_empleado_id = fields.Many2one(
        'flota.empleado', string='Nuevo Empleado (Reemplazo)', required=True,
        help="Empleado que recibirá los equipos: se creará una acta nueva en borrador a su nombre."
    )

    count_entregados = fields.Integer(string='Cantidad Entregados', compute='_compute_counts')
    count_devueltos = fields.Integer(string='Cantidad Devueltos', compute='_compute_counts')
    copiar_entregados = fields.Boolean(
        string='Copiar Equipos Nuevos Entregados', default=True,
        help="Copia a la nueva acta las líneas de la sección 'Datos de Equipo Nuevo Entregado'."
    )
    copiar_devueltos = fields.Boolean(
        string='Copiar Equipos Recibidos por IT (Devolución)', default=True,
        help="Copia a la nueva acta las líneas de la sección 'Equipos Recibidos por IT'."
    )
    nota = fields.Char(
        string='Nota de la Reasignación',
        help="Se agregará como comentario en el historial de ambas actas (opcional)."
    )

    @api.depends('entrega_id.linea_ids', 'entrega_id.linea_devuelta_ids')
    def _compute_counts(self):
        for rec in self:
            rec.count_entregados = len(rec.entrega_id.linea_ids)
            rec.count_devueltos = len(rec.entrega_id.linea_devuelta_ids)

    @api.constrains('nuevo_empleado_id', 'entrega_id')
    def _check_empleado_distinto(self):
        for rec in self:
            if rec.entrega_id and rec.nuevo_empleado_id and rec.nuevo_empleado_id == rec.entrega_id.empleado_id:
                raise UserError(_('Seleccione un empleado distinto al que ya tiene esta acta.'))

    def action_confirmar_reasignacion(self):
        self.ensure_one()
        origen = self.entrega_id
        nuevo_empleado = self.nuevo_empleado_id
        if not origen:
            raise UserError(_('No se encontró el acta de origen.'))
        if not nuevo_empleado:
            raise UserError(_('Seleccione el empleado que recibirá los equipos.'))
        if nuevo_empleado == origen.empleado_id:
            raise UserError(_('Seleccione un empleado distinto al que ya tiene esta acta.'))
        if not self.copiar_entregados and not self.copiar_devueltos:
            raise UserError(_('Seleccione al menos un tipo de equipo para copiar (entregados y/o devueltos).'))

        default_vals = {
            'empleado_id': nuevo_empleado.id,
            'estado': 'draft',
            'fecha': fields.Date.context_today(self),
            'reasignado_de_id': origen.id,
        }
        if not self.copiar_entregados:
            default_vals['linea_ids'] = []
        if not self.copiar_devueltos:
            default_vals['linea_devuelta_ids'] = []

        nueva_acta = origen.copy(default=default_vals)

        nota_extra = (': %s' % self.nota) if self.nota else ''
        origen.message_post(body=_(
            '🔁 Se reasignaron equipos de esta acta al empleado <b>%(empleado)s</b> en la nueva acta '
            '<a href="#" data-oe-model="flota.entrega.equipo" data-oe-id="%(id)s">%(nombre)s</a>%(nota)s'
        ) % {
            'empleado': nuevo_empleado.name,
            'id': nueva_acta.id,
            'nombre': nueva_acta.name,
            'nota': nota_extra,
        })
        nueva_acta.message_post(body=_(
            '🔁 Esta acta fue generada por reasignación de equipos desde la acta '
            '<a href="#" data-oe-model="flota.entrega.equipo" data-oe-id="%(id)s">%(nombre)s</a> '
            '(empleado anterior: <b>%(empleado_anterior)s</b>)%(nota)s'
        ) % {
            'id': origen.id,
            'nombre': origen.name,
            'empleado_anterior': origen.empleado_id.name,
            'nota': nota_extra,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Acta Reasignada'),
            'res_model': 'flota.entrega.equipo',
            'view_mode': 'form',
            'res_id': nueva_acta.id,
            'target': 'current',
        }
