{
    'name': 'Gestión de Flota y Empleados (n8n Integrated)',
    'version': '19.0.1.6.0',
    'category': 'Human Resources',
    'summary': 'Registro profesional de empleados, cargos, flota telefónica, ubicaciones, auditoría completa e integración con n8n.',
    'description': """
    Módulo profesional para Odoo 19:
    - Registro de Empleados, Departamentos y Ubicaciones.
    - Auditoría completa e historial de cambios en vivo (Chatter & Tracking).
    - Métricas detalladas por departamento/ubicación.
    - Adaptación responsiva garantizada en formularios (100% zoom en cualquier resolución).
    - Botón de Sincronizar centralizado en Ajustes de n8n.
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
