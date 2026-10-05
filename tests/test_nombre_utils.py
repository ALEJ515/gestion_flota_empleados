import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    'flota_nombre_utils', Path(__file__).resolve().parents[1] / 'models' / 'nombre_utils.py',
)
utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(utils)


class TestNombreUtils(unittest.TestCase):
    def test_capitalization_and_spacing(self):
        self.assertEqual(
            utils.normalizar_nombre('  VENTAS   CANAL TRADICIONAL  '),
            'Ventas Canal Tradicional',
        )

    def test_accented_names(self):
        self.assertEqual(utils.normalizar_nombre('JOSÉ MARÍA MUÑOZ'), 'José María Muñoz')

    def test_preserved_acronyms(self):
        self.assertEqual(utils.normalizar_nombre('CEDI NORTE IT TI UPS'), 'CEDI Norte IT TI UPS')

    def test_punctuation(self):
        self.assertEqual(utils.normalizar_nombre("ANA-MARÍA O'NEILL"), "Ana-María O'Neill")

    def test_idempotence(self):
        for name in ('Ventas Canal Tradicional', 'CEDI Norte', 'José María', False, None, ''):
            normalized = utils.normalizar_nombre(name)
            self.assertEqual(utils.normalizar_nombre(normalized), normalized)

    def test_lookup_key_matches_case_and_spacing(self):
        self.assertEqual(utils.clave_nombre('  VENTAS\t CANAL  TRADICIONAL '),
                         utils.clave_nombre('Ventas Canal Tradicional'))

    def test_lookup_key_preserves_literal_wildcards(self):
        self.assertEqual(utils.clave_nombre('Área_100%'), 'área_100%')
        self.assertNotEqual(utils.clave_nombre('Área_100%'), utils.clave_nombre('ÁreaX1000'))


if __name__ == '__main__':
    unittest.main()
