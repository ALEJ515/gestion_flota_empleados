from odoo import models, fields


class FlotaTipoEquipo(models.Model):
    _name = 'flota.tipo.equipo'
    _description = 'Tipo de Equipo (Catálogo)'
    _order = 'name asc'

    name = fields.Char(string='Tipo de Equipo', required=True, index=True)
    descripcion = fields.Char(string='Descripción', help="Detalle adicional opcional, ej. marca o familia típica.")
    active = fields.Boolean(default=True, string='Activo')
    es_licencia = fields.Boolean(
        string='Es Tipo de Licencia',
        default=False,
        help="Actívelo si este tipo corresponde a una licencia o plan (no un equipo físico). Al usarlo en una "
             "línea de un acta de entrega, el campo 'Marca' se reemplaza por la selección del catálogo "
             "'Tipos de Licencia', y esa línea se imprime aparte en la sección 'Datos de Licencias Asignadas' "
             "del PDF, en formato de línea completa en vez de columnas."
    )

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Ya existe un tipo de equipo registrado con este nombre.'),
    ]
