from odoo import models, fields, api
from odoo.exceptions import ValidationError


class FlotaEquipoMarca(models.Model):
    _name = 'flota.equipo.marca'
    _description = 'Marca de Equipos'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'flota.import.mixin']
    _order = 'name asc'
    _flota_import_autocrear = True

    name = fields.Char(string='Marca', required=True, index=True, tracking=True)
    descripcion = fields.Char(string='Descripción / Notas', tracking=True)
    active = fields.Boolean(default=True, string='Activo', tracking=True)

    modelo_ids = fields.One2many(
        'flota.equipo.modelo',
        'marca_id',
        string='Modelos Registrados'
    )
    total_modelos = fields.Integer(
        string='Total Modelos',
        compute='_compute_total_modelos',
        store=True
    )

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Ya existe una marca registrada con este nombre.'),
    ]

    @api.depends('modelo_ids')
    def _compute_total_modelos(self):
        for rec in self:
            rec.total_modelos = len(rec.modelo_ids)


class FlotaEquipoModelo(models.Model):
    _name = 'flota.equipo.modelo'
    _description = 'Modelo de Equipos'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'flota.import.mixin']
    _order = 'marca_id asc, name asc'

    name = fields.Char(string='Modelo', required=True, index=True, tracking=True)
    marca_id = fields.Many2one(
        'flota.equipo.marca',
        string='Marca',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True
    )
    tipo_equipo_id = fields.Many2one(
        'flota.tipo.equipo',
        string='Tipo de Equipo Típico',
        ondelete='set null',
        tracking=True,
        help="Tipo de equipo asociado comúnmente a este modelo (ej. Celular / Flota, Laptop, Monitor, etc.). Opcional."
    )
    descripcion = fields.Char(string='Descripción / Especificaciones', tracking=True)
    active = fields.Boolean(default=True, string='Activo', tracking=True)

    _sql_constraints = [
        ('marca_name_uniq', 'unique(marca_id, name)', 'Ya existe este modelo registrado para la misma marca.'),
    ]

    @api.model
    def _flota_import_buscar_existente(self, fila):
        """Un modelo se identifica por nombre + marca (el mismo nombre puede repetirse en marcas distintas)."""
        nombre = fila.get('name')
        if not isinstance(nombre, str) or not nombre.strip():
            return self.browse()
        dominio = [('name', '=ilike', nombre.strip())]
        marca = fila.get('marca_id')
        if isinstance(marca, str) and marca.strip():
            dominio.append(('marca_id.name', '=ilike', marca.strip()))
        encontrados = self.with_context(active_test=False).search(dominio, limit=2)
        return encontrados if len(encontrados) == 1 else self.browse()

    @api.depends('name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.name or ''
