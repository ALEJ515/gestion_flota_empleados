from odoo.tests import TransactionCase, tagged


CAMPOS = [
    'id', 'name', 'estado_asignacion', 'departamento_id', 'subdepartamento_id',
    'ubicacion_id', 'ruta_id', 'cargo', 'numero_flota', 'plan_datos_id',
]
CAMPOS_NUEVOS = [
    'name', 'cargo', 'numero_flota', 'departamento_id', 'subdepartamento_id',
    'ubicacion_id', 'ruta_id', 'plan_datos_id',
]
CREAR_TODO = {
    campo: True for campo in (
        'departamento_id', 'subdepartamento_id', 'ubicacion_id', 'ruta_id', 'plan_datos_id', 'marca_id',
    )
}


@tagged('post_install', '-at_install')
class TestImportRoundTrip(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.trad = env['flota.departamento'].create({'name': 'Canal Tradicional RT'})
        cls.mod = env['flota.departamento'].create({'name': 'Canal Moderno RT'})
        cls.norte_trad = env['flota.subdepartamento'].create({'name': 'Norte', 'departamento_id': cls.trad.id})
        cls.norte_mod = env['flota.subdepartamento'].create({'name': 'Norte', 'departamento_id': cls.mod.id})
        cls.ubicacion = env['flota.ubicacion'].create({'name': 'CEDI Norte RT'})
        cls.ruta = env['flota.ruta'].create({'name': 'NTP_01_RT'})
        cls.plan = env['flota.plan.datos'].create({'name': 'Plan RT 10GB'})
        cls.ana = env['flota.empleado'].create({
            'name': 'Ana Roundtrip', 'cargo': 'Vendedora', 'numero_flota': '8095550601',
            'departamento_id': cls.trad.id, 'subdepartamento_id': cls.norte_trad.id,
            'ubicacion_id': cls.ubicacion.id, 'ruta_id': cls.ruta.id, 'plan_datos_id': cls.plan.id,
        })
        cls.luis = env['flota.empleado'].create({
            'name': 'Luis Roundtrip', 'cargo': 'Vendedor', 'numero_flota': '8095550602',
            'departamento_id': cls.mod.id, 'subdepartamento_id': cls.norte_mod.id,
        })
        cls.libre = env['flota.empleado'].create({
            'numero_flota': '8095550603', 'estado_asignacion': 'disponible',
            'departamento_id': cls.mod.id,
        })
        cls.empleados = cls.ana | cls.luis | cls.libre

    def _errores(self, resultado):
        return [m for m in resultado['messages'] if m['type'] == 'error']

    def _importar(self, campos, filas, **contexto):
        return self.env['flota.empleado'].with_context(import_file=True, **contexto).load(campos, filas)

    def test_unchanged_export_reimports_without_errors(self):
        exportado = self.empleados.export_data(CAMPOS)['datas']
        resultado = self._importar(CAMPOS, exportado)
        self.assertFalse(self._errores(resultado), resultado['messages'])
        self.assertEqual(set(resultado['ids']), set(self.empleados.ids))
        self.assertEqual(self.luis.subdepartamento_id, self.norte_mod)
        self.assertEqual(self.ana.subdepartamento_id, self.norte_trad)
        self.assertEqual(self.libre.estado_asignacion, 'disponible')
        self.assertEqual(self.env['flota.subdepartamento'].search_count([('name', '=', 'Norte')]), 2)

    def test_export_without_id_column_updates_by_phone_number(self):
        campos = [c for c in CAMPOS if c != 'id']
        exportado = self.empleados.export_data(campos)['datas']
        count = self.env['flota.empleado'].search_count([])
        resultado = self._importar(campos, exportado)
        self.assertFalse(self._errores(resultado), resultado['messages'])
        self.assertEqual(self.env['flota.empleado'].search_count([]), count)

    def test_archived_references_still_import(self):
        self.mod.active = False
        self.norte_mod.active = False
        self.ruta.active = False
        exportado = self.empleados.export_data(CAMPOS)['datas']
        resultado = self._importar(CAMPOS, exportado)
        self.assertFalse(self._errores(resultado), resultado['messages'])
        self.assertEqual(self.luis.departamento_id, self.mod)
        self.assertEqual(self.ana.ruta_id, self.ruta)

    def test_references_with_other_case_resolve_to_existing_records(self):
        resultado = self._importar(
            ['numero_flota', 'departamento_id', 'subdepartamento_id', 'ruta_id'],
            [[self.luis.numero_flota, 'CANAL TRADICIONAL RT', 'NORTE', 'ntp_01_rt']],
        )
        self.assertFalse(self._errores(resultado), resultado['messages'])
        self.assertEqual(self.luis.departamento_id, self.trad)
        self.assertEqual(self.luis.subdepartamento_id, self.norte_trad)
        self.assertEqual(self.luis.ruta_id, self.ruta)

    def test_missing_references_are_not_created_unless_odoo_is_told_to(self):
        resultado = self._importar(
            CAMPOS_NUEVOS,
            [['Pedro Nuevo RT', 'Analista', '8095550611', 'Mercadeo Nuevo RT', 'Centro RT',
              'CEDI Nuevo RT', 'RUTA-NUEVA-RT', 'Plan Nuevo RT']],
        )
        self.assertTrue(self._errores(resultado))
        self.assertFalse(resultado['ids'])
        for modelo, nombre in (
            ('flota.departamento', 'Mercadeo Nuevo RT'), ('flota.ubicacion', 'CEDI Nuevo RT'),
            ('flota.ruta', 'RUTA-NUEVA-RT'), ('flota.plan.datos', 'Plan Nuevo RT'),
        ):
            self.assertFalse(self.env[modelo].with_context(active_test=False).search([('name', '=', nombre)]), modelo)

    def test_odoo_create_option_creates_missing_references_in_the_right_department(self):
        resultado = self._importar(
            CAMPOS_NUEVOS,
            [
                ['Pedro Nuevo RT', 'Analista', '8095550611', 'MERCADEO NUEVO RT', 'Centro RT',
                 'CEDI Nuevo RT', 'RUTA-NUEVA-RT', 'Plan Nuevo RT'],
                ['Sara Nueva RT', 'Analista', '8095550612', 'mercadeo nuevo rt', 'CENTRO RT',
                 'cedi nuevo rt', 'ruta-nueva-rt', 'plan nuevo rt'],
            ],
            name_create_enabled_fields=CREAR_TODO,
        )
        self.assertFalse(self._errores(resultado), resultado['messages'])
        departamento = self.env['flota.departamento'].search([('nombre_busqueda', '=', 'mercadeo nuevo rt')])
        self.assertEqual(len(departamento), 1)
        pedro, sara = self.env['flota.empleado'].browse(resultado['ids'])
        self.assertEqual(pedro.departamento_id, departamento)
        self.assertEqual(pedro.subdepartamento_id.departamento_id, departamento)
        self.assertEqual(pedro.subdepartamento_id, sara.subdepartamento_id)
        self.assertEqual(pedro.ubicacion_id, sara.ubicacion_id)
        self.assertEqual(pedro.ruta_id, sara.ruta_id)
        self.assertEqual(pedro.plan_datos_id, sara.plan_datos_id)

    def test_subdepartment_created_under_the_existing_department_of_the_row(self):
        resultado = self._importar(
            ['numero_flota', 'departamento_id', 'subdepartamento_id'],
            [[self.luis.numero_flota, 'canal moderno rt', 'Sur RT']],
            name_create_enabled_fields=CREAR_TODO,
        )
        self.assertFalse(self._errores(resultado), resultado['messages'])
        self.assertEqual(self.luis.subdepartamento_id.departamento_id, self.mod)
        self.assertEqual(self.luis.subdepartamento_id.name, 'Sur Rt')

    def test_odoo_skip_and_empty_options_still_work(self):
        filas = [['Persona Vacia RT', 'Analista', '8095550621', 'Departamento Inexistente RT']]
        campos = ['name', 'cargo', 'numero_flota', 'departamento_id']
        vacio = self._importar(campos, filas, import_set_empty_fields=['departamento_id'])
        self.assertFalse(self._errores(vacio), vacio['messages'])
        persona = self.env['flota.empleado'].browse(vacio['ids'])
        self.assertFalse(persona.departamento_id)

        filas = [['Persona Omitida RT', 'Analista', '8095550622', 'Departamento Inexistente RT']]
        omitido = self._importar(campos, filas, import_skip_records=['departamento_id'])
        self.assertFalse(self._errores(omitido), omitido['messages'])
        self.assertFalse(self.env['flota.empleado'].search([('numero_flota', '=', '809 555-0622')]))

    def test_ambiguous_subdepartment_without_department_is_a_row_error(self):
        resultado = self._importar(
            ['name', 'cargo', 'numero_flota', 'subdepartamento_id'],
            [['Persona Ambigua RT', 'Analista', '8095550631', 'Norte']],
        )
        self.assertTrue(self._errores(resultado))
        self.assertFalse(resultado['ids'])
        self.assertFalse(self.env['flota.empleado'].search([('numero_flota', '=', '809 555-0631')]))

    def test_files_without_assignment_state_or_with_blank_cells_import(self):
        campos = ['name', 'cargo', 'numero_flota']
        nuevo = self._importar(campos, [['Nuevo Sin Estado RT', 'Analista', '8095550651']])
        self.assertFalse(self._errores(nuevo), nuevo['messages'])
        self.assertEqual(self.env['flota.empleado'].browse(nuevo['ids']).estado_asignacion, 'asignada')

        campos = ['name', 'cargo', 'numero_flota', 'estado_asignacion', 'estado']
        resultado = self._importar(campos, [
            ['Nuevo Celdas Vacias RT', 'Analista', '8095550652', '', ''],
            ['', '', self.libre.numero_flota, '', ''],
        ])
        self.assertFalse(self._errores(resultado), resultado['messages'])
        creado = self.env['flota.empleado'].browse(resultado['ids'][0])
        self.assertEqual((creado.estado_asignacion, creado.estado), ('asignada', 'active'))
        self.assertEqual(self.libre.estado_asignacion, 'disponible')

    def test_catalog_exports_reimport_without_errors(self):
        for modelo, campos in (
            ('flota.departamento', ['id', 'name', 'code', 'ubicacion_id']),
            ('flota.subdepartamento', ['id', 'name', 'departamento_id']),
            ('flota.ruta', ['id', 'name', 'tipo', 'ubicacion_id']),
            ('flota.ubicacion', ['id', 'name', 'code']),
            ('flota.plan.datos', ['id', 'name', 'operador']),
        ):
            registros = self.env[modelo].search([])
            exportado = registros.export_data(campos)['datas']
            resultado = self.env[modelo].with_context(import_file=True).load(campos, exportado)
            self.assertFalse(self._errores(resultado), (modelo, resultado['messages']))

    def test_model_import_can_create_missing_brand(self):
        campos, filas = ['name', 'marca_id'], [['Modelo X RT', 'Marca Nueva RT']]
        sin_crear = self.env['flota.equipo.modelo'].with_context(import_file=True).load(campos, filas)
        self.assertTrue(self._errores(sin_crear))
        resultado = self.env['flota.equipo.modelo'].with_context(
            import_file=True, name_create_enabled_fields=CREAR_TODO,
        ).load(campos, filas)
        self.assertFalse(self._errores(resultado), resultado['messages'])
        self.assertEqual(self.env['flota.equipo.modelo'].browse(resultado['ids']).marca_id.name, 'Marca Nueva RT')
