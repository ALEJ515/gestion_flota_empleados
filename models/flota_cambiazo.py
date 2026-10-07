from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

from .flota_empleado import MESES_CAMBIAZO_1, MESES_CAMBIAZO_2


class FlotaCambiazo(models.Model):
    _name = 'flota.cambiazo'
    _description = 'Historial de Cambiazos de Equipo'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'fecha desc, id desc'

    empleado_id = fields.Many2one(
        'flota.empleado',
        string='Empleado',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True
    )
    numero_flota = fields.Char(related='empleado_id.numero_flota', string='Número Flota', store=True)
    departamento_id = fields.Many2one(related='empleado_id.departamento_id', string='Departamento', store=True)
    ubicacion_id = fields.Many2one(related='empleado_id.ubicacion_id', string='Ubicación', store=True)
    plan_datos_id = fields.Many2one(
        'flota.plan.datos',
        string='Plan de Datos',
        ondelete='set null',
        tracking=True,
        help="Plan que tenía el número al momento del cambiazo."
    )
    fecha = fields.Date(
        string='Fecha del Cambiazo',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        help="Desde esta fecha vuelven a contarse los 12 y 18 meses del número."
    )
    fecha_cambiazo_anterior = fields.Date(
        string='Cambiazo Anterior',
        readonly=True,
        help="Fecha del cambiazo previo del número al momento de registrar este."
    )
    meses_desde_anterior = fields.Integer(
        string='Meses desde el Anterior',
        compute='_compute_tipo_cambiazo',
        store=True
    )
    tipo_cambiazo = fields.Selection([
        ('inicial', 'Primer Registro'),
        ('anticipado', 'Anticipado (< 12 meses)'),
        ('12', 'A los 12 meses'),
        ('18', 'A los 18 meses'),
    ], string='Tipo de Cambiazo', compute='_compute_tipo_cambiazo', store=True)

    marca_anterior_id = fields.Many2one('flota.equipo.marca', string='Marca Anterior', ondelete='set null')
    modelo_anterior_id = fields.Many2one(
        'flota.equipo.modelo', string='Modelo Anterior', ondelete='set null',
        domain="[('marca_id', '=?', marca_anterior_id)]"
    )
    imei_anterior = fields.Char(string='IMEI / Serie Anterior')
    marca_nueva_id = fields.Many2one('flota.equipo.marca', string='Marca Nueva', ondelete='set null', tracking=True)
    modelo_nuevo_id = fields.Many2one(
        'flota.equipo.modelo', string='Modelo Nuevo', ondelete='set null', tracking=True,
        domain="[('marca_id', '=?', marca_nueva_id)]"
    )
    imei_nuevo = fields.Char(string='IMEI / Serie Nuevo', tracking=True)
    notas = fields.Text(string='Notas')
    user_id = fields.Many2one('res.users', string='Registrado por', default=lambda self: self.env.user, readonly=True)

    @api.depends('fecha', 'fecha_cambiazo_anterior')
    def _compute_tipo_cambiazo(self):
        for rec in self:
            if not rec.fecha or not rec.fecha_cambiazo_anterior or rec.fecha <= rec.fecha_cambiazo_anterior:
                rec.meses_desde_anterior = 0
                rec.tipo_cambiazo = 'inicial'
                continue
            diff = relativedelta(rec.fecha, rec.fecha_cambiazo_anterior)
            meses = diff.years * 12 + diff.months
            rec.meses_desde_anterior = meses
            if meses >= MESES_CAMBIAZO_2:
                rec.tipo_cambiazo = '18'
            elif meses >= MESES_CAMBIAZO_1:
                rec.tipo_cambiazo = '12'
            else:
                rec.tipo_cambiazo = 'anticipado'

    @api.depends('empleado_id.name', 'fecha')
    def _compute_display_name(self):
        for rec in self:
            fecha = fields.Date.to_string(rec.fecha) if rec.fecha else ''
            rec.display_name = f"{rec.empleado_id.name or ''} - {fecha}".strip(' -')

    @api.onchange('empleado_id')
    def _onchange_empleado_id(self):
        if self.empleado_id and not self.plan_datos_id:
            self.plan_datos_id = self.empleado_id.plan_datos_id

    @api.onchange('modelo_anterior_id')
    def _onchange_modelo_anterior_id(self):
        if self.modelo_anterior_id:
            self.marca_anterior_id = self.modelo_anterior_id.marca_id

    @api.onchange('modelo_nuevo_id')
    def _onchange_modelo_nuevo_id(self):
        if self.modelo_nuevo_id:
            self.marca_nueva_id = self.modelo_nuevo_id.marca_id

    @api.constrains('empleado_id')
    def _check_plan_datos(self):
        for rec in self:
            if rec.empleado_id.estado_asignacion != 'asignada':
                raise ValidationError(_(
                    'No se puede registrar un cambiazo para una línea disponible. '
                    'Asigne primero el número a una persona.'
                ))
            if not rec.empleado_id.plan_datos_id and not rec.plan_datos_id:
                raise ValidationError(_(
                    'El número de %s no tiene Plan de Datos. El cambiazo solo aplica a números con plan; '
                    'asigne primero el Plan de Datos al empleado.') % rec.empleado_id.name)

    @api.model_create_multi
    def create(self, vals_list):
        Empleado = self.env['flota.empleado']
        for vals in vals_list:
            empleado = Empleado.browse(vals.get('empleado_id'))
            if empleado:
                vals.setdefault('plan_datos_id', empleado.plan_datos_id.id or False)
                vals.setdefault('fecha_cambiazo_anterior', empleado.fecha_ultimo_cambiazo or False)
        records = super().create(vals_list)
        for rec in records:
            empleado = rec.empleado_id
            if not empleado.fecha_ultimo_cambiazo or rec.fecha >= empleado.fecha_ultimo_cambiazo:
                empleado.fecha_ultimo_cambiazo = rec.fecha
            equipo = rec.modelo_nuevo_id.display_name or rec.marca_nueva_id.name or ''
            empleado.message_post(body=_(
                'Cambiazo registrado el %(fecha)s%(equipo)s. El conteo de 12/18 meses inicia desde esta fecha.',
                fecha=fields.Date.to_string(rec.fecha),
                equipo=(_(' (equipo nuevo: %s)') % equipo) if equipo else '',
            ))
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'fecha' in vals or 'empleado_id' in vals:
            self.mapped('empleado_id')._sincronizar_fecha_ultimo_cambiazo()
        return res

    def unlink(self):
        empleados = self.mapped('empleado_id')
        res = super().unlink()
        empleados.exists()._sincronizar_fecha_ultimo_cambiazo()
        return res


class FlotaEmpleadoCambiazo(models.Model):
    _inherit = 'flota.empleado'

    def _sincronizar_fecha_ultimo_cambiazo(self):
        """Tras editar/eliminar un cambiazo, la fecha del empleado pasa a ser la del cambiazo más reciente."""
        for emp in self:
            fechas = emp.cambiazo_ids.mapped('fecha')
            if fechas:
                ultima = max(fechas)
                if emp.fecha_ultimo_cambiazo != ultima:
                    emp.fecha_ultimo_cambiazo = ultima
