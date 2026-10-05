from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestNombreImport(TransactionCase):
    def setUp(self):
        super().setUp()
        self.departamento = self.env['flota.departamento'].create({'name': 'VENTAS CANAL PRUEBA'})
        self.subdepartamento = self.env['flota.subdepartamento'].create({
            'name': 'VENTAS CANAL PRUEBA NORTE', 'departamento_id': self.departamento.id,
        })
        self.ubicacion = self.env['flota.ubicacion'].create({'name': 'CEDI PRUEBA NORTE'})
        self.empleado = self.env['flota.empleado'].create({
            'name': 'JOSÉ PRUEBA NOMBRES', 'cargo': 'Analista', 'numero_flota': '8095550301',
        })

    def test_create_and_write_normalize_only_names(self):
        self.assertEqual(self.departamento.name, 'Ventas Canal Prueba')
        self.assertEqual(self.subdepartamento.name, 'Ventas Canal Prueba Norte')
        self.assertEqual(self.ubicacion.name, 'CEDI Prueba Norte')
        self.assertEqual(self.empleado.name, 'José Prueba Nombres')
        self.empleado.name = '  ANA   MARÍA PRUEBA  '
        self.assertEqual(self.empleado.name, 'Ana María Prueba')
        self.departamento.write({'name': '  VENTAS  IT PRUEBA ', 'code': 'CT-AB'})
        self.assertEqual(self.departamento.name, 'Ventas IT Prueba')
        self.assertEqual(self.departamento.code, 'CT-AB')
        ruta = self.env['flota.ruta'].create({'name': 'NTP0103-AB'})
        marca = self.env['flota.equipo.marca'].create({'name': 'HP'})
        modelo = self.env['flota.equipo.modelo'].create({'name': 'ProBook 450 G10', 'marca_id': marca.id})
        self.assertEqual(ruta.name, 'NTP0103-AB')
        self.assertEqual(modelo.name, 'ProBook 450 G10')

    def test_uppercase_references_import_without_duplicates(self):
        xmlid = self.empleado.export_data(['id'])['datas'][0][0]
        result = self.env['flota.empleado'].load(
            ['id', 'departamento_id', 'subdepartamento_id', 'ubicacion_id'],
            [[xmlid, ' VENTAS  CANAL PRUEBA ', 'VENTAS CANAL PRUEBA NORTE', 'CEDI PRUEBA NORTE']],
        )
        self.assertFalse([m for m in result['messages'] if m['type'] == 'error'])
        self.assertEqual(self.empleado.departamento_id, self.departamento)
        self.assertEqual(self.empleado.subdepartamento_id, self.subdepartamento)
        self.assertEqual(self.empleado.ubicacion_id, self.ubicacion)

    def test_catalog_upsert_without_id_and_duplicate_guard(self):
        result = self.env['flota.departamento'].load(
            ['name', 'code'], [['  VENTAS   CANAL PRUEBA ', 'CT-XYZ']],
        )
        self.assertFalse([m for m in result['messages'] if m['type'] == 'error'])
        self.assertEqual(result['ids'], self.departamento.ids)
        self.assertEqual(self.departamento.name, 'Ventas Canal Prueba')
        self.departamento.active = False
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['flota.departamento'].create({'name': 'ventas canal prueba'})

    def test_existing_legacy_name_resolves_without_renaming(self):
        self.env.flush_all()
        self.cr.execute(
            'UPDATE flota_departamento SET name = %s WHERE id = %s',
            ['VENTAS CANAL PRUEBA', self.departamento.id],
        )
        self.departamento.invalidate_recordset(['name'])
        result = self.departamento.name_search('  ventas canal prueba ', operator='=')
        self.assertEqual(result, [(self.departamento.id, 'VENTAS CANAL PRUEBA')])
        self.assertEqual(self.departamento.name, 'VENTAS CANAL PRUEBA')

    def test_ambiguous_subdepartment_requires_external_id(self):
        otro = self.env['flota.departamento'].create({'name': 'OTRO CANAL PRUEBA'})
        division = self.env['flota.subdepartamento'].create({
            'name': self.subdepartamento.name, 'departamento_id': otro.id,
        })
        with self.assertRaises(ValidationError):
            self.env['flota.subdepartamento'].name_search(self.subdepartamento.name.upper(), operator='=')
        result = self.env['flota.empleado'].load(
            ['numero_flota', 'departamento_id/id', 'subdepartamento_id/id'],
            [[self.empleado.numero_flota, otro.export_data(['id'])['datas'][0][0],
              division.export_data(['id'])['datas'][0][0]]],
        )
        self.assertFalse([m for m in result['messages'] if m['type'] == 'error'])
        self.assertEqual(self.empleado.subdepartamento_id, division)

    def test_exact_match_does_not_interpret_wildcards(self):
        departamento = self.env['flota.departamento'].create({'name': 'ÁREA_100% PRUEBA'})
        self.env['flota.departamento'].create({'name': 'ÁREAX1000 PRUEBA'})
        matches = departamento.name_search('área_100% prueba', operator='=')
        self.assertEqual([rec_id for rec_id, _ in matches], departamento.ids)
