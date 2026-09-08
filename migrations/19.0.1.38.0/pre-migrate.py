"""Ensure new tax & CDT exclusion columns exist in PostgreSQL database."""


def migrate(cr, version):
    cr.execute(
        """
        ALTER TABLE flota_factura_conciliacion 
        ADD COLUMN IF NOT EXISTS subtotal_factura NUMERIC,
        ADD COLUMN IF NOT EXISTS base_gravable_itbis NUMERIC,
        ADD COLUMN IF NOT EXISTS base_gravable_cdt NUMERIC,
        ADD COLUMN IF NOT EXISTS base_gravable_isc NUMERIC,
        ADD COLUMN IF NOT EXISTS ajustes_excluidos_cdt NUMERIC;
        """
    )
