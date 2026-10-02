from datetime import date
from unittest.mock import patch

from odoo import fields
from odoo.tests import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEmployeeActa(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = cls.env['flota.plan.datos'].create({'name': 'Plan prueba sincronizacion'})
        cls.employee = cls.env['flota.empleado'].create({
            'name': 'Empleado prueba sincronizacion',
            'cargo': 'Vendedor',
            'numero_flota': '8095550101',
            'plan_datos_id': cls.plan.id,
        })
        cls.acta = cls.env['flota.entrega.equipo'].create({'empleado_id': cls.employee.id})
        cls.other_acta = cls.env['flota.entrega.equipo'].create({
            'empleado_id': cls.employee.id, 'estado': 'confirmado',
        })

    def test_import_last_upgrade_date_and_computed_columns(self):
        columns = ['id', 'fecha_ultimo_cambiazo', 'estado_cambiazo', 'ultima_facturacion_monto']
        template = self.employee.export_data(columns)['datas']
        self.assertEqual(len(template), 1)
        xmlid = template[0][0]
        count = self.env['flota.empleado'].search_count([])
        with patch.object(fields.Date, 'context_today', return_value=date(2026, 10, 2)):
            for value, expected in (
                ('2025-10-02', 'apto_12'),
                ('2025-04-02', 'apto_18'),
                ('2026-10-01', 'en_espera'),
            ):
                result = self.env['flota.empleado'].load(columns, [[xmlid, value, 'sin_plan', '999999']])
                self.assertFalse([m for m in result['messages'] if m['type'] == 'error'])
                self.assertEqual(self.employee.fecha_ultimo_cambiazo, fields.Date.to_date(value))
                self.assertEqual(self.employee.estado_cambiazo, expected)
        self.assertEqual(self.env['flota.empleado'].search_count([]), count)
        self.assertFalse(self.employee.ultima_facturacion_monto)
        self.assertFalse(self.employee.cambiazo_ids)
        self.employee.plan_datos_id = False
        self.assertEqual(self.employee.estado_cambiazo, 'sin_plan')

    def test_import_without_id_updates_existing_employee(self):
        result = self.env['flota.empleado'].load(
            ['numero_flota', 'fecha_ultimo_cambiazo'],
            [[self.employee.numero_flota, '2025-10-01']],
        )
        self.assertFalse([m for m in result['messages'] if m['type'] == 'error'])
        self.assertEqual(result['ids'], self.employee.ids)
        self.assertEqual(self.employee.fecha_ultimo_cambiazo, date(2025, 10, 1))

    def test_invalid_date_import_does_not_change_employee(self):
        self.employee.fecha_ultimo_cambiazo = date(2025, 10, 1)
        result = self.env['flota.empleado'].load(
            ['id', 'fecha_ultimo_cambiazo'],
            [[self.employee._flota_import_xmlid(), 'not-a-date']],
        )
        self.assertTrue([m for m in result['messages'] if m['type'] == 'error'])
        self.assertEqual(self.employee.fecha_ultimo_cambiazo, date(2025, 10, 1))

    def test_employee_changes_reach_all_actas(self):
        ruta = self.env['flota.ruta'].create({'name': 'Ruta prueba sincronizacion'})
        ubicacion = self.env['flota.ubicacion'].create({'name': 'Localidad prueba sincronizacion'})
        self.employee.write({
            'name': 'Empleado actualizado por perfil',
            'cargo': 'Analista',
            'ruta_id': ruta.id,
            'ubicacion_id': ubicacion.id,
            'numero_flota': '8095550102',
        })
        for acta in self.acta | self.other_acta:
            self.assertEqual(acta.recibido_por, self.employee.name)
            self.assertEqual(acta.cargo, 'Analista')
            self.assertEqual(acta.ruta_id, ruta)
            self.assertEqual(acta.ubicacion_id, ubicacion)
            self.assertEqual(acta.telefono_flota, self.employee.numero_flota)
            self.assertFalse(acta.mostrar_ruta)
        self.assertEqual(self.other_acta.estado, 'confirmado')

    def test_acta_changes_update_employee_and_sibling(self):
        ruta = self.env['flota.ruta'].create({'name': 'Ruta editada desde acta'})
        ubicacion = self.env['flota.ubicacion'].create({'name': 'Localidad editada desde acta'})
        self.acta.write({
            'recibido_por': 'Empleado actualizado por acta',
            'cargo': 'Distribuidor',
            'ruta_id': ruta.id,
            'ubicacion_id': ubicacion.id,
            'telefono_flota': '8095550103',
        })
        self.assertEqual(self.employee.name, self.acta.recibido_por)
        self.assertEqual(self.employee.cargo, 'Distribuidor')
        self.assertEqual(self.employee.ruta_id, ruta)
        self.assertEqual(self.employee.ubicacion_id, ubicacion)
        self.assertEqual(self.employee.numero_flota, '809 555-0103')
        self.assertEqual(self.other_acta.recibido_por, self.employee.name)
        self.assertEqual(self.other_acta.telefono_flota, self.employee.numero_flota)
        self.assertTrue(self.other_acta.mostrar_ruta)

    def test_selecting_employee_does_not_change_previous_employee(self):
        replacement = self.env['flota.empleado'].create({
            'name': 'Empleado reemplazo prueba',
            'cargo': 'Analista',
            'numero_flota': '8095550104',
        })
        original_name = self.employee.name
        with Form(self.acta) as form:
            form.empleado_id = replacement
            self.assertEqual(form.recibido_por, replacement.name)
            self.assertEqual(form.telefono_flota, replacement.numero_flota)
        self.assertEqual(self.employee.name, original_name)
        self.assertEqual(self.acta.recibido_por, replacement.name)
        copied = self.other_acta.copy(default={'empleado_id': replacement.id})
        self.assertEqual(copied.recibido_por, replacement.name)
        self.assertEqual(self.employee.name, original_name)

    def test_model_name_and_report_without_duplicate_brand(self):
        brand = self.env['flota.equipo.marca'].create({'name': 'Marca prueba PDF'})
        model = self.env['flota.equipo.modelo'].create({'name': 'Modelo prueba PDF', 'marca_id': brand.id})
        self.assertEqual(model.display_name, model.name)
        equipment = self.env['flota.tipo.equipo'].create({'name': 'Equipo prueba PDF'})
        self.env['flota.entrega.equipo.linea'].create([
            {
                'entrega_id': self.acta.id, 'tipo_equipo': equipment.id,
                'tipo_movimiento': movement, 'marca_id': brand.id, 'modelo_id': model.id,
            }
            for movement in ('entregado', 'devuelto')
        ])
        self.employee.name = 'Empleado actualizado para PDF'
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'gestion_flota_empleados.action_report_flota_entrega_equipo', self.acta.ids,
        )
        html = html.decode()
        self.assertIn(self.employee.name, html)
        self.assertIn(model.name, html)
        self.assertIn(brand.name, html)
        self.assertNotIn(f'{brand.name} {model.name}', html)
