from odoo import models, fields


class FlotaTipoEquipo(models.Model):
    _name = 'flota.tipo.equipo'
    _description = 'Equipo o Licencia (Catálogo)'
    _order = 'name asc'

    name = fields.Char(string='Equipo o Licencia', required=True, index=True)
    descripcion = fields.Char(string='Descripción', help="Detalle adicional opcional, ej. marca o familia típica.")
    active = fields.Boolean(default=True, string='Activo')
    es_licencia = fields.Boolean(
        string='Es Licencia',
        default=False,
        help="Actívelo si este registro corresponde a una licencia o plan (no un equipo físico). Al usarlo en "
             "una línea de un acta de entrega, ya no será necesario seleccionar Marca ni Estado (queda en "
             "'N/A' automáticamente), y esa línea se imprime aparte en la sección 'Datos de Licencias "
             "Asignadas' del PDF, en formato de línea completa en vez de columnas."
    )

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Ya existe un equipo o licencia registrado con este nombre.'),
    ]
