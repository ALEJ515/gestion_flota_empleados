"""Ensure new columns exist in PostgreSQL database."""


def migrate(cr, version):
    cr.execute(
        """
        ALTER TABLE flota_empleado 
        ADD COLUMN IF NOT EXISTS penultima_facturacion_periodo VARCHAR;
        """
    )
    cr.execute(
        """
        ALTER TABLE flota_factura_departamento_resumen 
        ADD COLUMN IF NOT EXISTS currency_id INTEGER;
        """
    )
