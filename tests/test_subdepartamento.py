from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSubdepartamento(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.departamento = cls.env['flota.departamento'].create({'name': 'Canal prueba tradicional'})
        cls.otro_departamento = cls.env['flota.departamento'].create({'name': 'Canal prueba moderno'})
        cls.norte, cls.sur, cls.otro_sub = cls.env['flota.subdepartamento'].create([
            {'name': 'Tradicional prueba Norte', 'departamento_id': cls.departamento.id},
            {'name': 'Tradicional prueba Sur', 'departamento_id': cls.departamento.id},
            {'name': 'Moderno prueba Norte', 'departamento_id': cls.otro_departamento.id},
        ])
        cls.empleado, cls.otro_empleado = cls.env['flota.empleado'].create([
            {
                'name': 'Empleado prueba subdepartamento',
                'cargo': 'Analista', 'numero_flota': '8095550201',
                'departamento_id': cls.departamento.id, 'subdepartamento_id': cls.norte.id,
            },
            {
                'name': 'Otro empleado prueba subdepartamento',
                'cargo': 'Analista', 'numero_flota': '8095550202',
                'departamento_id': cls.otro_departamento.id, 'subdepartamento_id': cls.otro_sub.id,
            },
        ])

    def test_subdepartamento_is_optional(self):
        self.empleado.subdepartamento_id = False
        self.assertEqual(self.empleado.departamento_id, self.departamento)

    def test_department_change_clears_only_incompatible_assignment(self):
        (self.empleado | self.otro_empleado).write({'departamento_id': self.departamento.id})
        self.assertEqual(self.empleado.subdepartamento_id, self.norte)
        self.assertFalse(self.otro_empleado.subdepartamento_id)
        self.empleado.departamento_id = False
        self.assertFalse(self.empleado.subdepartamento_id)

    def test_invalid_explicit_assignment_is_rejected(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.empleado.write({'subdepartamento_id': self.otro_sub.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.empleado.write({
                'departamento_id': self.otro_departamento.id, 'subdepartamento_id': self.norte.id,
            })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['flota.empleado'].create({
                'name': 'Empleado division invalida', 'cargo': 'Analista',
                'numero_flota': '8095550203', 'subdepartamento_id': self.norte.id,
            })

    def test_form_filters_and_clears_subdepartamento(self):
        with Form(self.empleado) as form:
            form.departamento_id = self.otro_departamento
            self.assertFalse(form.subdepartamento_id)
            form.subdepartamento_id = self.otro_sub
        self.assertEqual(self.empleado.subdepartamento_id, self.otro_sub)

    def test_reparenting_division_with_archived_employees_is_rejected(self):
        self.empleado.active = False
        self.assertEqual(self.norte.total_empleados, 1)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.norte.departamento_id = self.otro_departamento
        self.empleado.subdepartamento_id = False
        self.norte.departamento_id = self.otro_departamento
        self.assertEqual(self.norte.departamento_id, self.otro_departamento)

    def test_invalid_subdepartment_import_reports_error(self):
        xmlid = self.empleado.export_data(['id'])['datas'][0][0]
        result = self.env['flota.empleado'].load(
            ['id', 'subdepartamento_id'], [[xmlid, self.otro_sub.name]],
        )
        self.assertTrue([m for m in result['messages'] if m['type'] == 'error'])
        self.assertEqual(self.empleado.subdepartamento_id, self.norte)

    def test_duplicate_name_in_department_including_archived(self):
        self.norte.active = False
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['flota.subdepartamento'].create({
                'name': self.norte.name.lower(), 'departamento_id': self.departamento.id,
            })
        division = self.env['flota.subdepartamento'].create({
            'name': self.norte.name, 'departamento_id': self.otro_departamento.id,
        })
        self.assertEqual(division.departamento_id, self.otro_departamento)

    def test_mass_update_assign_and_clear(self):
        wizard = self.env['flota.empleado.mass.update.wizard'].create({
            'empleado_ids': [(6, 0, self.empleado.ids)],
            'set_subdepartamento': True, 'subdepartamento_id': self.sur.id,
        })
        wizard.action_apply_mass_update()
        self.assertEqual(self.empleado.subdepartamento_id, self.sur)
        wizard.subdepartamento_id = False
        wizard.action_apply_mass_update()
        self.assertFalse(self.empleado.subdepartamento_id)

    def test_mass_update_mixed_departments_requires_department_change(self):
        wizard = self.env['flota.empleado.mass.update.wizard'].create({
            'empleado_ids': [(6, 0, (self.empleado | self.otro_empleado).ids)],
            'set_subdepartamento': True, 'subdepartamento_id': self.sur.id,
        })
        with self.assertRaises(UserError), self.cr.savepoint():
            wizard.action_apply_mass_update()
        wizard.write({'set_departamento': True, 'departamento_id': self.departamento.id})
        wizard.action_apply_mass_update()
        for emp in self.empleado | self.otro_empleado:
            self.assertEqual(emp.departamento_id, self.departamento)
            self.assertEqual(emp.subdepartamento_id, self.sur)

    def test_employee_excel_roundtrip(self):
        columns = ['id', 'subdepartamento_id/id']
        template = self.empleado.export_data(columns)['datas']
        sub_xmlid = self.sur.export_data(['id'])['datas'][0][0]
        template[0][1] = sub_xmlid
        result = self.env['flota.empleado'].load(columns, template)
        self.assertFalse([m for m in result['messages'] if m['type'] == 'error'])
        self.assertEqual(result['ids'], self.empleado.ids)
        self.assertEqual(self.empleado.subdepartamento_id, self.sur)
        result = self.env['flota.empleado'].load(
            ['numero_flota', 'subdepartamento_id'],
            [[self.empleado.numero_flota, self.norte.name]],
        )
        self.assertFalse([m for m in result['messages'] if m['type'] == 'error'])
        self.assertEqual(self.empleado.subdepartamento_id, self.norte)

    def test_catalog_import_matches_department_and_name(self):
        division = self.env['flota.subdepartamento'].create({
            'name': self.norte.name, 'departamento_id': self.otro_departamento.id,
        })
        result = self.env['flota.subdepartamento'].load(
            ['name', 'departamento_id', 'active'],
            [[division.name, self.otro_departamento.name, 'False']],
        )
        self.assertFalse([m for m in result['messages'] if m['type'] == 'error'])
        self.assertEqual(result['ids'], division.ids)
        self.assertTrue(self.norte.active)
        self.assertFalse(division.active)

    def test_panel_ranges_follow_department_and_preserve_totals(self):
        values = self.env['flota.empleado'].search_panel_select_multi_range(
            'subdepartamento_id',
            category_domain=[('departamento_id', '=', self.departamento.id)],
            comodel_domain=[('departamento_id', '=', self.departamento.id)],
            enable_counters=True,
        )['values']
        self.assertEqual({v['id'] for v in values}, {self.norte.id})
        self.assertEqual(values[0]['__count'], 1)
        self.empleado.subdepartamento_id = self.sur
        self.assertEqual(self.departamento.total_empleados, 1)
        self.assertEqual(self.sur.total_empleados, 1)
        self.assertEqual(self.norte.total_empleados, 0)
