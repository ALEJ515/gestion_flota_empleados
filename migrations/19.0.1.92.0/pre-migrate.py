from odoo.addons.gestion_flota_empleados.models.flota_schema import (
    prepare_employee_assignment_schema,
)


def migrate(cr, version):
    if not version:
        return
    prepare_employee_assignment_schema(cr)
