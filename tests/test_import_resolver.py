import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    'flota_import_resolver',
    Path(__file__).resolve().parents[1] / 'models' / 'flota_import_resolver.py',
)
resolver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolver)


class FakeProvider:
    def __init__(self, existentes=None, fallar=()):
        self.registros = {'dep': [], 'sub': [], 'ruta': []}
        self.siguiente = 100
        self.creados = []
        self.fallar = set(fallar)
        for comodel, nombre, padre, id_ in existentes or []:
            self.registros[comodel].append((self._clave(nombre), padre, id_))

    @staticmethod
    def _clave(texto):
        return ' '.join(texto.split()).casefold()

    def tiene_padre(self, comodel):
        return comodel == 'sub'

    def etiqueta_padre(self, comodel):
        return 'Departamento'

    def candidatos(self, comodel, texto):
        clave = self._clave(texto)
        return [(p, i) for c, p, i in self.registros[comodel] if c == clave]

    def crear(self, comodel, texto, padre_id):
        if texto in self.fallar:
            raise resolver.ErrorResolucion('sin permiso')
        self.siguiente += 1
        self.registros[comodel].append((self._clave(texto), padre_id or 0, self.siguiente))
        self.creados.append((comodel, texto, padre_id))
        return self.siguiente


COLUMNAS = {
    'departamento_id': {'comodel': 'dep', 'padre': None},
    'subdepartamento_id': {'comodel': 'sub', 'padre': 'departamento_id'},
    'ruta_id': {'comodel': 'ruta', 'padre': None},
}


class TestResolverReferencias(unittest.TestCase):
    def setUp(self):
        self.existentes = [
            ('dep', 'Canal Tradicional', 0, 1),
            ('dep', 'Canal Moderno', 0, 2),
            ('sub', 'Norte', 1, 11),
            ('sub', 'Norte', 2, 12),
            ('ruta', 'NTP_01', 0, 21),
        ]

    def correr(self, fields, data, **kwargs):
        proveedor = kwargs.pop('proveedor', None) or FakeProvider(self.existentes)
        fields = resolver.resolver_referencias(fields, data, COLUMNAS, proveedor, **kwargs)
        return fields, data, proveedor

    def test_resolves_names_case_insensitive_and_renames_columns(self):
        fields, data, _ = self.correr(
            ['id', 'departamento_id', 'ruta_id', 'name'],
            [['x.1', ' CANAL   moderno ', 'ntp_01', 'Ana']],
        )
        self.assertEqual(fields, ['id', 'departamento_id/.id', 'ruta_id/.id', 'name'])
        self.assertEqual(data, [['x.1', '2', '21', 'Ana']])

    def test_repeated_subdepartment_name_uses_row_department(self):
        _, data, _ = self.correr(
            ['departamento_id', 'subdepartamento_id'],
            [['Canal Tradicional', 'Norte'], ['canal moderno', 'NORTE']],
        )
        self.assertEqual(data, [['1', '11'], ['2', '12']])

    def test_subdepartment_column_can_precede_department_column(self):
        _, data, _ = self.correr(
            ['subdepartamento_id', 'departamento_id'], [['Norte', 'Canal Moderno']],
        )
        self.assertEqual(data, [['12', '2']])

    def test_missing_department_column_uses_existing_record_department(self):
        _, data, _ = self.correr(
            ['subdepartamento_id'], [['Norte'], ['Norte']],
            padre_existente=lambda fila, campo: 2 if fila == 0 else 1,
        )
        self.assertEqual(data, [['12'], ['11']])

    def test_ambiguous_subdepartment_without_department_is_reported(self):
        _, data, proveedor = self.correr(['subdepartamento_id'], [['Norte']])
        self.assertEqual(data, [['Norte [existe en varios; indique Departamento]']])
        self.assertFalse(proveedor.creados)

    def test_unique_subdepartment_resolves_without_department(self):
        proveedor = FakeProvider(self.existentes + [('sub', 'Sur', 1, 13)])
        _, data, _ = self.correr(['subdepartamento_id'], [['sur']], proveedor=proveedor)
        self.assertEqual(data, [['13']])

    def test_creates_missing_parent_before_child_and_only_once(self):
        _, data, proveedor = self.correr(
            ['subdepartamento_id', 'departamento_id', 'ruta_id'],
            [['Centro', 'Mercadeo Nuevo', 'RUTA-X'], ['centro', 'MERCADEO NUEVO', 'ruta-x']],
        )
        self.assertEqual(data[0], data[1])
        self.assertEqual(
            proveedor.creados,
            [('dep', 'Mercadeo Nuevo', None), ('ruta', 'RUTA-X', None), ('sub', 'Centro', 101)],
        )
        self.assertEqual(data[0], ['103', '101', '102'])

    def test_creates_subdepartment_in_existing_department(self):
        _, data, proveedor = self.correr(
            ['departamento_id', 'subdepartamento_id'], [['Canal Moderno', 'Sur']],
        )
        self.assertEqual(proveedor.creados, [('sub', 'Sur', 2)])
        self.assertEqual(data, [['2', '101']])

    def test_new_subdepartment_without_department_is_not_created(self):
        _, data, proveedor = self.correr(['subdepartamento_id'], [['Inexistente']])
        self.assertEqual(data, [['Inexistente [indique Departamento para crearlo]']])
        self.assertFalse(proveedor.creados)

    def test_creation_can_be_disabled(self):
        _, data, proveedor = self.correr(
            ['departamento_id'], [['Nuevo'], ['Canal Moderno']], crear=False,
        )
        self.assertEqual(data, [['Nuevo [no existe]'], ['2']])
        self.assertFalse(proveedor.creados)

    def test_creation_failure_is_reported_per_row(self):
        proveedor = FakeProvider(self.existentes, fallar=['Bloqueado'])
        _, data, _ = self.correr(
            ['departamento_id'], [['Bloqueado'], ['Canal Moderno']], proveedor=proveedor,
        )
        self.assertEqual(data, [['Bloqueado [sin permiso]'], ['2']])

    def test_blank_cells_are_cleared_not_created(self):
        fields, data, proveedor = self.correr(
            ['name', 'departamento_id', 'ruta_id'], [['Ana', '   ', ''], ['Luis', None, 'NTP_01']],
        )
        self.assertEqual(fields, ['name', 'departamento_id/.id', 'ruta_id/.id'])
        self.assertEqual(data, [['Ana', '', ''], ['Luis', '', '21']])
        self.assertFalse(proveedor.creados)

    def test_unlisted_columns_and_row_count_are_preserved(self):
        fields, data, _ = self.correr(['name', 'cargo'], [['Ana', 'Jefe']])
        self.assertEqual(fields, ['name', 'cargo'])
        self.assertEqual(data, [['Ana', 'Jefe']])


if __name__ == '__main__':
    unittest.main()
