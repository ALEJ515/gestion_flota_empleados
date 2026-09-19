# -*- coding: utf-8 -*-
"""Antes de que el ORM intente convertir la columna 'tipo_equipo' de texto (Selection)
a un entero (Many2one), renombramos la columna existente a un respaldo temporal.
Así el ORM crea una columna nueva y vacía para el Many2one, y en el post-migrate
rellenamos sus valores a partir del respaldo, sin perder ni romper datos existentes.
"""


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'flota_entrega_equipo_linea' AND column_name = 'tipo_equipo'
    """)
    row = cr.fetchone()
    if row and row[0] == 'character varying':
        cr.execute("""
            ALTER TABLE flota_entrega_equipo_linea
            RENAME COLUMN tipo_equipo TO tipo_equipo_old_txt
        """)
