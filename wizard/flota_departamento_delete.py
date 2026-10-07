from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.nombre_utils import clave_nombre


class FlotaDepartamentoDeleteWizard(models.TransientModel):
    _name = 'flota.departamento.delete.wizard'
    _description = 'Eliminar Departamento y trasladar sus registros a N/A'

    departamento_id = fields.Many2one(
        'flota.departamento', string='Departamento a eliminar', required=True, readonly=True,
    )
    departamento_destino_id = fields.Many2one(
        'flota.departamento', string='Departamento destino', readonly=True,
    )
    cantidad_lineas = fields.Integer(compute='_compute_impacto')
    cantidad_subdepartamentos = fields.Integer(compute='_compute_impacto')
    cantidad_resumenes = fields.Integer(compute='_compute_impacto')

    @api.depends('departamento_id')
    def _compute_impacto(self):
        for rec in self:
            source_id = rec.departamento_id.id
            rec.cantidad_lineas = self.env['flota.empleado'].with_context(active_test=False).search_count([
                ('departamento_id', '=', source_id),
            ]) if source_id else 0
            rec.cantidad_subdepartamentos = self.env['flota.subdepartamento'].with_context(active_test=False).search_count([
                ('departamento_id', '=', source_id),
            ]) if source_id else 0
            rec.cantidad_resumenes = self.env['flota.factura.departamento.resumen'].search_count([
                ('departamento_id', '=', source_id),
            ]) if source_id else 0
            rec.departamento_destino_id = self.env['flota.departamento'].with_context(active_test=False).search(
                [('nombre_busqueda', '=', clave_nombre('N/A'))], limit=1,
            ) if source_id else False

    def _get_or_create_na_department(self):
        Departamento = self.env['flota.departamento'].with_context(active_test=False)
        destino = Departamento.search([('nombre_busqueda', '=', clave_nombre('N/A'))], limit=1)
        if destino:
            if not destino.active:
                destino.active = True
            return destino
        return self.env['flota.departamento'].create({
            'name': 'N/A',
            'code': 'N/A',
        })

    def _transfer_employees_and_subdepartments(self, source, target):
        Employee = self.env['flota.empleado'].with_context(active_test=False)
        Subdepartamento = self.env['flota.subdepartamento'].with_context(active_test=False)
        employees = Employee.search([('departamento_id', '=', source.id)])
        subdepartments = Subdepartamento.search([('departamento_id', '=', source.id)])

        for subdepartment in subdepartments:
            assigned = employees.filtered(lambda emp: emp.subdepartamento_id == subdepartment)
            target_subdepartment = Subdepartamento.search([
                ('departamento_id', '=', target.id),
                ('nombre_busqueda', '=', subdepartment.nombre_busqueda),
            ], limit=1)
            if target_subdepartment:
                if not target_subdepartment.active:
                    target_subdepartment.active = True
                if assigned:
                    assigned.write({
                        'departamento_id': target.id,
                        'subdepartamento_id': target_subdepartment.id,
                    })
                subdepartment.unlink()
                continue

            if assigned:
                assigned.write({'departamento_id': target.id, 'subdepartamento_id': False})
            subdepartment.write({'departamento_id': target.id})
            if assigned:
                assigned.write({'subdepartamento_id': subdepartment.id})

        remaining = employees.filtered(lambda emp: emp.departamento_id == source)
        if remaining:
            remaining.write({'departamento_id': target.id, 'subdepartamento_id': False})

    def _transfer_invoice_summaries(self, source, target):
        Summary = self.env['flota.factura.departamento.resumen']
        source_summaries = Summary.search([('departamento_id', '=', source.id)])
        for summary in source_summaries:
            existing = Summary.search([
                ('conciliacion_id', '=', summary.conciliacion_id.id),
                ('departamento_id', '=', target.id),
                ('ubicacion_id', '=', summary.ubicacion_id.id or False),
                ('id', '!=', summary.id),
            ], limit=1)
            if existing:
                existing.write({
                    'cantidad_empleados': existing.cantidad_empleados + summary.cantidad_empleados,
                    'monto_subtotal': existing.monto_subtotal + summary.monto_subtotal,
                    'monto_total': existing.monto_total + summary.monto_total,
                    'porcentaje_gasto': existing.porcentaje_gasto + summary.porcentaje_gasto,
                })
                summary.unlink()
            else:
                summary.write({'departamento_id': target.id})

    def action_confirm_transfer_and_delete(self):
        self.ensure_one()
        if not self.env.user.has_group('gestion_flota_empleados.group_flota_manager'):
            raise UserError(_('Solo un Administrador de Flota puede eliminar un departamento.'))
        source = self.departamento_id
        if not source.exists():
            raise UserError(_('El departamento ya no existe.'))
        if source.nombre_busqueda == clave_nombre('N/A'):
            raise UserError(_('El departamento N/A es el destino de reasignación y no se puede eliminar desde aquí.'))

        target = self._get_or_create_na_department()
        self._transfer_employees_and_subdepartments(source, target)
        self._transfer_invoice_summaries(source, target)
        source.unlink()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Departamento eliminado'),
                'message': _(
                    'Los números, subdepartamentos y resúmenes históricos asociados se trasladaron a N/A.'
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
