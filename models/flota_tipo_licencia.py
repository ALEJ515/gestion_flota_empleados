from odoo import models, fields


class FlotaTipoLicencia(models.Model):
    _name = 'flota.tipo.licencia'
    _description = 'Tipo de Licencia (Catálogo)'
    _order = 'name asc'

    name = fields.Char(string='Tipo de Licencia', required=True, index=True,
        help="Ej. Plan Corporativo Ilimitado, Plan Datos Básico, Microsoft 365, Antivirus Corporativo, etc.")
    descripcion = fields.Char(string='Descripción', help="Detalle adicional opcional, ej. proveedor o alcance de la licencia.")
    active = fields.Boolean(default=True, string='Activo')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Ya existe un tipo de licencia registrado con este nombre.'),
    ]
