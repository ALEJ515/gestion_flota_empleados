from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAvailableLines(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.departamento = cls.env['flota.departamento'].create({'name': 'Ventas disponible prueba'})
        cls.subdepartamento = cls.env['flota.subdepartamento'].create({
            'name': 'Ventas norte disponible prueba',
            'departamento_id': cls.departamento.id,
        })
        cls.employee = cls.env['flota.empleado'].create({
            'name': 'Empleado asignado prueba disponible',
            'cargo': 'Ejecutivo de ventas',
            'numero_flota': '8095550401',
            'departamento_id': cls.departamento.id,
            'subdepartamento_id': cls.subdepartamento.id,
        })

    def test_legacy_placeholder_creates_empty_available_line(self):
        line = self.env['flota.empleado'].create({
            'name': '  DISPONIBLE 2 ',
            'cargo': 'Asignación automática',
            'numero_flota': '8095550402',
            'departamento_id': self.departamento.id,
            'subdepartamento_id': self.subdepartamento.id,
            'ruta_id': self.env['flota.ruta'].create({'name': 'RUTA DISPONIBLE PRUEBA'}).id,
        })
        self.assertEqual(line.estado_asignacion, 'disponible')
        self.assertFalse(line.name)
        self.assertFalse(line.cargo)
        self.assertFalse(line.subdepartamento_id)
        self.assertFalse(line.ruta_id)
        self.assertEqual(line.departamento_id, self.departamento)
        self.assertEqual(line.numero_flota, '809 555-0402')
        self.assertIn('Disponible', line.display_name)
        self.assertIn(line.numero_flota, line.display_name)

    def test_legacy_placeholder_import_updates_by_number(self):
        line = self.env['flota.empleado'].create({
            'name': 'Disponible 5', 'numero_flota': '8095550403',
            'cargo': 'Asignación automática',
        })
        count = self.env['flota.empleado'].search_count([])
        result = self.env['flota.empleado'].load(
            ['name', 'numero_flota', 'cargo'],
            [['DISPONIBLE 5', line.numero_flota, 'Asignación automática']],
        )
        self.assertFalse([message for message in result['messages'] if message['type'] == 'error'])
        self.assertEqual(result['ids'], line.ids)
        self.assertEqual(self.env['flota.empleado'].search_count([]), count)
        self.assertEqual(line.estado_asignacion, 'disponible')
        self.assertFalse(line.name)
        self.assertFalse(line.cargo)

    def test_assign_available_line_to_person(self):
        line = self.env['flota.empleado'].create({
            'name': 'Disponible', 'numero_flota': '8095550404',
        })
        line.write({'name': 'María Pérez', 'cargo': 'Vendedora'})
        self.assertEqual(line.estado_asignacion, 'asignada')
        self.assertEqual(line.name, 'María Pérez')
        self.assertEqual(line.cargo, 'Vendedora')
        self.assertEqual(line.numero_flota, '809 555-0404')

    def test_available_line_can_be_created_from_empty_employee_name(self):
        line = self.env['flota.empleado'].create({
            'numero_flota': '8095550405',
            'estado_asignacion': 'disponible',
        })
        self.assertEqual(line.estado_asignacion, 'disponible')
        self.assertFalse(line.name)
        self.assertFalse(line.cargo)

    def test_assigned_line_requires_person_and_cargo(self):
        for values in (
            {'name': False, 'cargo': False},
            {'name': 'Persona sin cargo', 'cargo': False},
        ):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.env['flota.empleado'].create({
                    'numero_flota': '8095550499',
                    'estado_asignacion': 'asignada',
                    **values,
                })

    def test_available_line_cannot_receive_acta_or_be_liberated_after_acta(self):
        available = self.env['flota.empleado'].create({
            'name': 'Disponible 8', 'numero_flota': '8095550406',
        })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['flota.entrega.equipo'].create({'empleado_id': available.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['flota.cambiazo'].create({'empleado_id': available.id})

        acta = self.env['flota.entrega.equipo'].create({'empleado_id': self.employee.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            self.employee.write({'estado_asignacion': 'disponible'})
        self.assertEqual(acta.empleado_id, self.employee)
        self.assertEqual(self.employee.estado_asignacion, 'asignada')

    def test_search_can_filter_available_phone_lines(self):
        available = self.env['flota.empleado'].create({
            'name': 'Disponible 9', 'numero_flota': '8095550407',
        })
        found = self.env['flota.empleado'].search([('estado_asignacion', '=', 'disponible')])
        self.assertIn(available, found)
        self.assertNotIn(self.employee, found)

    def test_move_department_and_subdepartments_to_na(self):
        available = self.env['flota.empleado'].create({
            'name': 'Disponible 10',
            'numero_flota': '8095550408',
            'departamento_id': self.departamento.id,
            'subdepartamento_id': self.subdepartamento.id,
        })
        wizard = self.env['flota.departamento.delete.wizard'].create({
            'departamento_id': self.departamento.id,
        })
        action = wizard.action_confirm_transfer_and_delete()
        na = self.env['flota.departamento'].with_context(active_test=False).search(
            [('nombre_busqueda', '=', 'n/a')], limit=1,
        )
        self.assertFalse(self.departamento.exists())
        self.assertTrue(na)
        self.assertEqual(self.employee.departamento_id, na)
        self.assertEqual(available.departamento_id, na)
        self.assertEqual(self.employee.subdepartamento_id.departamento_id, na)
        self.assertEqual(action['params']['type'], 'success')

    def test_merge_duplicate_subdepartments_during_department_transfer(self):
        na = self.env['flota.departamento'].create({'name': 'N/A'})
        na_subdepartment = self.env['flota.subdepartamento'].create({
            'name': 'Norte disponible prueba',
            'departamento_id': na.id,
        })
        source = self.env['flota.departamento'].create({'name': 'Departamento a eliminar prueba'})
        source_subdepartment = self.env['flota.subdepartamento'].create({
            'name': 'NORTE DISPONIBLE PRUEBA',
            'departamento_id': source.id,
        })
        employee = self.env['flota.empleado'].create({
            'name': 'Empleado subdepartamento a mover',
            'cargo': 'Analista',
            'numero_flota': '8095550409',
            'departamento_id': source.id,
            'subdepartamento_id': source_subdepartment.id,
        })
        wizard = self.env['flota.departamento.delete.wizard'].create({'departamento_id': source.id})
        wizard.action_confirm_transfer_and_delete()
        self.assertEqual(employee.departamento_id, na)
        self.assertEqual(employee.subdepartamento_id, na_subdepartment)
        self.assertFalse(source_subdepartment.exists())

    def test_department_direct_delete_reports_safe_action(self):
        with self.assertRaises(UserError), self.cr.savepoint():
            self.departamento.unlink()
        self.assertTrue(self.departamento.exists())
