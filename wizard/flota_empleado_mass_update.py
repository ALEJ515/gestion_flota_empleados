from odoo import models, fields, api, _
from odoo.exceptions import UserError

class FlotaEmpleadoMassUpdateWizard(models.TransientModel):
    _name = 'flota.empleado.mass.update.wizard'
    _description = 'Asistente de Asignación Masiva de Empleados'

    empleado_ids = fields.Many2many(
        'flota.empleado',
        string='Empleados Seleccionados',
        default=lambda self: self.env.context.get('active_ids', [])
    )

    set_ubicacion = fields.Boolean(string='Modificar CEDI / Ubicación')
    ubicacion_id = fields.Many2one('flota.ubicacion', string='CEDI / Ubicación', ondelete='set null')

    set_ruta = fields.Boolean(string='Modificar Ruta')
    ruta_id = fields.Many2one('flota.ruta', string='Ruta', ondelete='set null')

    set_departamento = fields.Boolean(string='Modificar Departamento')
    departamento_id = fields.Many2one('flota.departamento', string='Departamento', ondelete='set null')

    set_subdepartamento = fields.Boolean(string='Modificar Subdepartamento')
    subdepartamento_id = fields.Many2one(
        'flota.subdepartamento', string='Subdepartamento', ondelete='set null',
        help="Deje vacío para retirar la asignación. Para asignarlo a empleados de distintos "
             "departamentos, marque también Modificar Departamento."
    )
    departamentos_disponibles_ids = fields.Many2many(
        'flota.departamento', compute='_compute_departamentos_disponibles'
    )

    @api.depends('set_departamento', 'departamento_id', 'empleado_ids.departamento_id')
    def _compute_departamentos_disponibles(self):
        for rec in self:
            rec.departamentos_disponibles_ids = (
                rec.departamento_id if rec.set_departamento else rec.empleado_ids.mapped('departamento_id')
            )

    @api.onchange('set_departamento', 'departamento_id', 'empleado_ids')
    def _onchange_departamento_subdepartamento(self):
        for rec in self:
            if rec.subdepartamento_id and (
                rec.subdepartamento_id.departamento_id not in rec.departamentos_disponibles_ids
            ):
                rec.subdepartamento_id = False

    set_cargo = fields.Boolean(string='Modificar Cargo')
    cargo = fields.Char(string='Cargo')

    set_plan_datos = fields.Boolean(string='Modificar Plan de Datos')
    plan_datos_id = fields.Many2one('flota.plan.datos', string='Plan de Datos', ondelete='set null')

    set_fecha_cambiazo = fields.Boolean(string='Modificar Fecha Último Cambiazo')
    fecha_ultimo_cambiazo = fields.Date(string='Fecha Último Cambiazo')

    set_estado = fields.Boolean(string='Modificar Estado')
    estado = fields.Selection([
        ('draft', 'Borrador'),
        ('active', 'Activo'),
        ('inactive', 'Inactivo')
    ], string='Estado')

    count_empleados = fields.Integer(compute='_compute_count_empleados', string='Cantidad de Empleados')

    @api.depends('empleado_ids')
    def _compute_count_empleados(self):
        for record in self:
            record.count_empleados = len(record.empleado_ids)

    def action_apply_mass_update(self):
        self.ensure_one()
        if not self.empleado_ids:
            raise UserError(_('No hay empleados seleccionados para actualizar.'))

        vals = {}
        changes_desc = []

        if self.set_ubicacion:
            if not self.ubicacion_id:
                raise UserError(_('Por favor seleccione una Ubicación/CEDI válida.'))
            vals['ubicacion_id'] = self.ubicacion_id.id
            changes_desc.append(f"CEDI/Ubicación: {self.ubicacion_id.name}")

        if self.set_ruta:
            if not self.ruta_id:
                raise UserError(_('Por favor seleccione una Ruta válida.'))
            vals['ruta_id'] = self.ruta_id.id
            changes_desc.append(f"Ruta: {self.ruta_id.name}")

        if self.set_departamento:
            if not self.departamento_id:
                raise UserError(_('Por favor seleccione un Departamento válido.'))
            vals['departamento_id'] = self.departamento_id.id
            changes_desc.append(f"Departamento: {self.departamento_id.name}")

        if self.set_subdepartamento:
            if self.subdepartamento_id:
                departamento = self.subdepartamento_id.departamento_id
                incompatible = (
                    departamento != self.departamento_id if self.set_departamento
                    else any(emp.departamento_id != departamento for emp in self.empleado_ids)
                )
                if incompatible:
                    raise UserError(_(
                        'El subdepartamento seleccionado no corresponde a todos los empleados. '
                        'Seleccione empleados del mismo departamento o modifique también el Departamento.'
                    ))
            vals['subdepartamento_id'] = self.subdepartamento_id.id or False
            changes_desc.append(
                f"Subdepartamento: {self.subdepartamento_id.name if self.subdepartamento_id else 'Sin asignar'}"
            )

        if self.set_cargo:
            if not self.cargo or not self.cargo.strip():
                raise UserError(_('Por favor introduzca un Cargo válido.'))
            vals['cargo'] = self.cargo.strip()
            changes_desc.append(f"Cargo: {self.cargo.strip()}")

        if self.set_plan_datos:
            vals['plan_datos_id'] = self.plan_datos_id.id or False
            changes_desc.append(f"Plan de Datos: {self.plan_datos_id.name if self.plan_datos_id else 'Sin asignar'}")

        if self.set_fecha_cambiazo:
            vals['fecha_ultimo_cambiazo'] = self.fecha_ultimo_cambiazo or False
            fecha_txt = fields.Date.to_string(self.fecha_ultimo_cambiazo) if self.fecha_ultimo_cambiazo else 'Sin fecha'
            changes_desc.append(f"Fecha Último Cambiazo: {fecha_txt}")

        if self.set_estado:
            if not self.estado:
                raise UserError(_('Por favor seleccione un Estado válido.'))
            vals['estado'] = self.estado
            estado_str = dict(self._fields['estado'].selection).get(self.estado)
            changes_desc.append(f"Estado: {estado_str}")

        if not vals:
            raise UserError(_('Por favor active al menos una casilla de verificación para aplicar cambios masivos.'))

        # Apply update
        self.empleado_ids.write(vals)

        # Log chatter note on updated employees
        note = _("<b>Asignación Masiva Aplicada:</b><br/>") + "<br/>".join(changes_desc)
        for emp in self.empleado_ids:
            emp.message_post(body=note)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Asignación Masiva Exitosa'),
                'message': _('Se han actualizado %s empleados correctamente.') % len(self.empleado_ids),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
