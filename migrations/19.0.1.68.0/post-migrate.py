# -*- coding: utf-8 -*-
"""Después de que Odoo terminó de crear la tabla 'flota_tipo_equipo' y la nueva columna
entera 'tipo_equipo' (Many2one) en 'flota_entrega_equipo_linea', migramos los datos
antiguos: creamos un tipo de equipo por cada valor de Selection que existía antes,
remapeamos las líneas existentes a su nuevo id y eliminamos la columna de respaldo.

También actualizamos los valores antiguos de 'estado_equipo' ('nueva'/'usada') a las
nuevas claves ('nuevo'/'usado') para que sigan viéndose correctamente con las nuevas
opciones de estado.
"""

# (clave_anterior, nombre_a_mostrar)
LEGACY_TIPO_EQUIPO = [
    ('celular', 'Celular'),
    ('tablet', 'Tablet'),
    ('laptop', 'Laptop'),
    ('impresora', 'Impresora'),
    ('accesorio', 'Accesorio'),
    ('otro', 'Otro'),
]


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'flota_entrega_equipo_linea' AND column_name = 'tipo_equipo_old_txt'
    """)
    if cr.fetchone():
        for key, label in LEGACY_TIPO_EQUIPO:
            cr.execute("""
                SELECT id FROM flota_tipo_equipo WHERE name = %s
            """, (label,))
            row = cr.fetchone()
            if row:
                tipo_id = row[0]
            else:
                cr.execute("""
                    INSERT INTO flota_tipo_equipo (name, active, create_date, write_date)
                    VALUES (%s, TRUE, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC')
                    RETURNING id
                """, (label,))
                tipo_id = cr.fetchone()[0]

            cr.execute("""
                UPDATE flota_entrega_equipo_linea
                SET tipo_equipo = %s
                WHERE tipo_equipo_old_txt = %s
            """, (tipo_id, key))

        cr.execute("""
            ALTER TABLE flota_entrega_equipo_linea DROP COLUMN tipo_equipo_old_txt
        """)

    # Remapeo de los antiguos valores de estado_equipo a las nuevas claves.
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'flota_entrega_equipo_linea' AND column_name = 'estado_equipo'
    """)
    if cr.fetchone():
        cr.execute("UPDATE flota_entrega_equipo_linea SET estado_equipo = 'nuevo' WHERE estado_equipo = 'nueva'")
        cr.execute("UPDATE flota_entrega_equipo_linea SET estado_equipo = 'usado' WHERE estado_equipo = 'usada'")
