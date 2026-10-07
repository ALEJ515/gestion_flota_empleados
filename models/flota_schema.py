"""Prepare legacy employee tables before ORM initialization reads new fields."""


def employee_assignment_column_missing(cr):
    cr.execute("""
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'flota_empleado'
           AND column_name = 'estado_asignacion'
    """)
    return cr.fetchone() is None


def prepare_employee_assignment_schema(cr):
    cr.execute("SELECT to_regclass('flota_empleado')")
    if not cr.fetchone()[0]:
        return

    cr.execute("""
        ALTER TABLE flota_empleado
            ADD COLUMN IF NOT EXISTS penultima_facturacion_periodo VARCHAR,
            ADD COLUMN IF NOT EXISTS estado_asignacion VARCHAR DEFAULT 'asignada'
    """)
    cr.execute("""
        UPDATE flota_empleado
           SET estado_asignacion = 'asignada'
         WHERE estado_asignacion IS NULL
    """)
    cr.execute("""
        ALTER TABLE flota_empleado
            ALTER COLUMN estado_asignacion SET NOT NULL,
            ALTER COLUMN name DROP NOT NULL,
            ALTER COLUMN cargo DROP NOT NULL
    """)
