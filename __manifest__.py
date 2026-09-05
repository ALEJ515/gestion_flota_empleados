{
    'name': 'Gestión de Flota y Empleados (Factura Claro Nativa)',
    'version': '19.0.1.21.0',
    'category': 'Human Resources',
    'summary': 'Registro profesional de empleados, cargos, flota telefónica, ubicaciones, conciliación financiera de facturas Claro 100% nativa.',
    'description': """
    Módulo profesional para Odoo 19:
    - Registro de Empleados, Departamentos y Ubicaciones.
    - Asistente de Asignación Masiva para CEDI/Departamento/Cargo/Estado.
    - Conciliación Financiera NATIVA de Facturas Claro (extracción avanzada de PDF dentro de Odoo).
    - Exportación a Excel en una sola hoja (.xlsx) y Reporte Imprimible PDF nativo.
    - Auditoría completa e historial de cambios en vivo (Chatter & Tracking).
    """,
    'author': 'PaulDev',
    'website': 'https://ui-control.com',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/flota_empleado_mass_update_views.xml',
        'views/flota_empleado_views.xml',
        'views/flota_departamento_views.xml',
        'views/flota_ubicacion_views.xml',
        'views/flota_factura_conciliacion_views.xml',
        'reports/flota_factura_conciliacion_report.xml',
        'views/res_config_settings_views.xml',
        'views/menu_views.xml',
        'data/demo_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'gestion_flota_empleados/static/src/css/flota_style.css',
        ],
    },
    'application': True,
    'installable': True,
    'auto_install': False,
}
