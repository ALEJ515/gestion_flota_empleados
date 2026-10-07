from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from .nombre_utils import clave_nombre
from .flota_import_resolver import SEPARADOR_PADRE


class FlotaSubdepartamento(models.Model):
    _name = 'flota.subdepartamento'
    _description = 'Subdepartamento de Flota'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'flota.nombre.mixin']
    _order = 'departamento_id, name, id'
    _flota_import_catalogo = True
    _flota_import_campo_padre = 'departamento_id'

    name = fields.Char(string='Subdepartamento', required=True, index=True, tracking=True)
    departamento_id = fields.Many2one(
        'flota.departamento', string='Departamento', required=True,
        ondelete='restrict', index=True, tracking=True
    )
    active = fields.Boolean(string='Activo', default=True, tracking=True)
    empleado_ids = fields.One2many(
        'flota.empleado', 'subdepartamento_id', string='Empleados'
    )
    total_empleados = fields.Integer(
        string='Total Empleados', compute='_compute_total_empleados', store=True
    )

    @api.depends('empleado_ids')
    def _compute_total_empleados(self):
        for rec in self:
            rec.total_empleados = len(rec.with_context(active_test=False).empleado_ids)

    @api.constrains('name', 'departamento_id')
    def _check_name_unique(self):
        for rec in self:
            if self.with_context(active_test=False).search_count([
                ('id', '!=', rec.id),
                ('departamento_id', '=', rec.departamento_id.id),
                ('nombre_busqueda', '=', rec.nombre_busqueda),
            ]):
                raise ValidationError(_(
                    'Ya existe el subdepartamento %(sub)s en %(departamento)s.',
                    sub=rec.name, departamento=rec.departamento_id.name,
                ))

    @api.constrains('departamento_id')
    def _check_empleados_departamento(self):
        for rec in self:
            if self.env['flota.empleado'].with_context(active_test=False).search_count([
                ('subdepartamento_id', '=', rec.id),
                ('departamento_id', '!=', rec.departamento_id.id),
            ]):
                raise ValidationError(_(
                    'No puede cambiar el departamento de %(sub)s mientras tenga empleados '
                    'asignados a otro departamento. Retire primero esas asignaciones.',
                    sub=rec.name,
                ))

    @api.model
    def name_search(self, name='', domain=None, operator='ilike', limit=100):
        # "Departamento / Subdepartamento" identifica sin ambigüedad una división con nombre repetido.
        if name and operator == '=' and SEPARADOR_PADRE in name:
            departamento, subdepartamento = name.split(SEPARADOR_PADRE, 1)
            encontrados = self.with_context(active_test=False).search([
                ('nombre_busqueda', '=', clave_nombre(subdepartamento)),
                ('departamento_id.nombre_busqueda', '=', clave_nombre(departamento)),
            ] + list(domain or []), limit=1)
            if encontrados:
                return [(rec.id, rec.display_name) for rec in encontrados]
        return super().name_search(name=name, domain=domain, operator=operator, limit=limit)

    @api.model
    def name_create(self, name):
        # Al importar, «Crear nuevos valores» crea la división dentro del Departamento indicado.
        if name and SEPARADOR_PADRE in name:
            departamento, subdepartamento = name.split(SEPARADOR_PADRE, 1)
            padre = self.env['flota.departamento'].with_context(active_test=False).search(
                [('nombre_busqueda', '=', clave_nombre(departamento))], limit=1,
            )
            if padre:
                rec = self.create({'name': subdepartamento, 'departamento_id': padre.id})
                return rec.id, rec.display_name
        return super().name_create(name)

    @api.model
    def _flota_import_buscar_existente(self, fila):
        nombre = fila.get('name')
        if not isinstance(nombre, str) or not nombre.strip():
            return self.browse()
        domain = [('nombre_busqueda', '=', clave_nombre(nombre))]
        departamento = fila.get('departamento_id')
        if isinstance(departamento, str) and departamento.strip():
            domain.append(('departamento_id.nombre_busqueda', '=', clave_nombre(departamento)))
        candidatos = self.with_context(active_test=False).search(domain, limit=2)
        if len(candidatos) > 1:
            raise ValidationError(_(
                'El subdepartamento "%s" existe en varios departamentos. Conserve su ID externo '
                'o incluya el Departamento para actualizarlo.'
            ) % nombre)
        return candidatos

    def action_view_empleados(self):
        self.ensure_one()
        return {
            'name': _('Empleados en %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'flota.empleado',
            'view_mode': 'list,kanban,form',
            'domain': [('subdepartamento_id', '=', self.id)],
            'context': {
                'default_departamento_id': self.departamento_id.id,
                'default_subdepartamento_id': self.id,
                'active_test': False,
            },
        }
