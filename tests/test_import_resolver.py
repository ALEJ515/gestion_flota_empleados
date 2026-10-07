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
    def __init__(self, registros):
        self.registros = registros

    def candidatos(self, comodel, texto):
        clave = ' '.join(texto.split()).casefold()
        return [(p, i, n) for c, n, p, i in self.registros.get(comodel, []) if c == clave]


def registro(nombre, padre, id_):
    return (nombre.casefold(), nombre, padre, id_)


COLUMNAS = {
    'departamento_id': {'comodel': 'dep', 'padre': None},
    'subdepartamento_id': {'comodel': 'sub', 'padre': 'departamento_id'},
    'ruta_id': {'comodel': 'ruta', 'padre': None},
}


class TestNormalizarReferencias(unittest.TestCase):
    def setUp(self):
        self.proveedor = FakeProvider({
            'dep': [registro('Canal Tradicional', 0, 1), registro('Canal Moderno', 0, 2)],
            'sub': [registro('Norte', 1, 11), registro('Norte', 2, 12), registro('Sur', 1, 13)],
            'ruta': [registro('NTP_01', 0, 21)],
        })

    def correr(self, fields, data, **kwargs):
        return resolver.normalizar_referencias(fields, data, COLUMNAS, self.proveedor, **kwargs)

    def test_existing_records_use_their_exact_name_and_keep_columns(self):
        fields, data = self.correr(
            ['id', 'departamento_id', 'ruta_id', 'name'],
            [['x.1', ' CANAL   moderno ', 'ntp_01', 'Ana']],
        )
        self.assertEqual(fields, ['id', 'departamento_id', 'ruta_id', 'name'])
        self.assertEqual(data, [['x.1', 'Canal Moderno', 'NTP_01', 'Ana']])

    def test_repeated_subdepartment_name_is_qualified_with_row_department(self):
        _, data = self.correr(
            ['departamento_id', 'subdepartamento_id'],
            [['CANAL TRADICIONAL', 'norte'], ['canal moderno', 'NORTE']],
        )
        self.assertEqual(data, [
            ['Canal Tradicional', 'Canal Tradicional / Norte'],
            ['Canal Moderno', 'Canal Moderno / Norte'],
        ])

    def test_subdepartment_column_is_moved_after_its_department(self):
        fields, data = self.correr(
            ['subdepartamento_id', 'name', 'departamento_id'], [['Norte', 'Ana', 'Canal Moderno']],
        )
        self.assertEqual(fields, ['name', 'departamento_id', 'subdepartamento_id'])
        self.assertEqual(data, [['Ana', 'Canal Moderno', 'Canal Moderno / Norte']])

    def test_missing_department_column_uses_existing_record_department(self):
        _, data = self.correr(
            ['subdepartamento_id'], [['Norte'], ['norte']],
            padre_existente=lambda fila, campo: (2, 'Canal Moderno') if fila == 0 else (1, 'Canal Tradicional'),
        )
        self.assertEqual(data, [['Canal Moderno / Norte'], ['Canal Tradicional / Norte']])

    def test_unknown_department_of_the_row_is_kept_so_odoo_can_offer_to_create_it(self):
        _, data = self.correr(
            ['departamento_id', 'subdepartamento_id'], [['Mercadeo Nuevo', 'Centro']],
        )
        self.assertEqual(data, [['Mercadeo Nuevo', 'Mercadeo Nuevo / Centro']])

    def test_new_subdepartment_in_existing_department_keeps_the_department(self):
        _, data = self.correr(
            ['departamento_id', 'subdepartamento_id'], [['canal moderno', 'Oeste']],
        )
        self.assertEqual(data, [['Canal Moderno', 'Canal Moderno / Oeste']])

    def test_unknown_values_without_department_are_left_untouched(self):
        _, data = self.correr(
            ['subdepartamento_id', 'ruta_id'], [['Norte', 'RUTA-NUEVA'], ['Inexistente', '']],
        )
        self.assertEqual(data, [['Norte', 'RUTA-NUEVA'], ['Inexistente', '']])

    def test_blank_cells_stay_blank_and_nothing_is_created(self):
        fields, data = self.correr(
            ['name', 'departamento_id', 'ruta_id'], [['Ana', '   ', ''], ['Luis', None, 'ntp_01']],
        )
        self.assertEqual(fields, ['name', 'departamento_id', 'ruta_id'])
        self.assertEqual(data, [['Ana', '', ''], ['Luis', '', 'NTP_01']])

    def test_without_catalog_columns_data_is_unchanged(self):
        fields, data = self.correr(['name', 'cargo'], [['Ana', 'Jefe']])
        self.assertEqual((fields, data), (['name', 'cargo'], [['Ana', 'Jefe']]))

    def test_input_is_not_mutated(self):
        original = [['Canal Moderno', 'norte']]
        self.correr(['departamento_id', 'subdepartamento_id'], original)
        self.assertEqual(original, [['Canal Moderno', 'norte']])


if __name__ == '__main__':
    unittest.main()
