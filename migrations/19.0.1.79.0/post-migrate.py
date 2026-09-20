# -*- coding: utf-8 -*-
"""'Datos Flota Recibida por TI' deja de ser un bloque fijo (Modelo/Serial/Estado, limitado a un
único equipo de tipo flota) y pasa a ser una tabla de líneas ('linea_devuelta_ids'), igual que
'Equipo Nuevo Entregado', para poder registrar varios equipos de cualquier tipo del catálogo
'Equipo o Licencias' (laptop, monitor, UPS, teléfono, etc.) en una devolución.

Este script:
1. Marca como 'entregado' cualquier línea existente en flota_entrega_equipo_linea que no tenga
   aún un valor en la nueva columna 'tipo_movimiento' (todas las líneas existentes hasta ahora
   eran, por diseño, equipos entregados).
2. Migra los datos que existían en las columnas fijas 'equipo_recibido_modelo',
   'equipo_recibido_serial' y 'estado_flota_recibida' de flota_entrega_equipo hacia una nueva
   línea en flota_entrega_equipo_linea con tipo_movimiento='devuelto', para no perder el
   historial de actas que ya tenían una flota devuelta registrada.
"""


def _column_exists(cr, table, column):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not version:
        return

    # 1. Todas las líneas ya existentes son, por diseño anterior, equipos entregados.
    if _column_exists(cr, 'flota_entrega_equipo_linea', 'tipo_movimiento'):
        cr.execute("""
            UPDATE flota_entrega_equipo_linea
            SET tipo_movimiento = 'entregado'
            WHERE tipo_movimiento IS NULL
        """)

    # 2. Migrar los datos fijos de "flota recibida" (si las columnas todavía existen físicamente)
    #    hacia una línea nueva de tipo 'devuelto'.
    columnas_viejas = ['equipo_recibido_modelo', 'equipo_recibido_serial', 'estado_flota_recibida']
    if not all(_column_exists(cr, 'flota_entrega_equipo', col) for col in columnas_viejas):
        return

    cr.execute("""
        SELECT id, equipo_recibido_modelo, equipo_recibido_serial, estado_flota_recibida
        FROM flota_entrega_equipo
        WHERE COALESCE(equipo_recibido_modelo, '') != ''
           OR COALESCE(equipo_recibido_serial, '') != ''
           OR COALESCE(estado_flota_recibida, '') != ''
    """)
    filas = cr.fetchall()
    if not filas:
        return

    # Catálogo a usar para las líneas migradas: "Flota (Teléfono)".
    cr.execute("SELECT id FROM flota_tipo_equipo WHERE name = %s", ('Flota (Teléfono)',))
    row = cr.fetchone()
    if row:
        tipo_equipo_id = row[0]
    else:
        cr.execute("""
            INSERT INTO flota_tipo_equipo (name, es_licencia, active, create_date, write_date)
            VALUES (%s, FALSE, TRUE, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC')
            RETURNING id
        """, ('Flota (Teléfono)',))
        tipo_equipo_id = cr.fetchone()[0]

    for entrega_id, modelo, serial, estado in filas:
        cr.execute("""
            INSERT INTO flota_entrega_equipo_linea
                (entrega_id, tipo_equipo, modelo, imei_serial, estado_equipo, cantidad,
                 tipo_movimiento, es_linea_licencia, create_date, write_date)
            VALUES (%s, %s, %s, %s, %s, 1, 'devuelto', FALSE,
                    now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC')
        """, (entrega_id, tipo_equipo_id, modelo or None, serial or None, estado or 'na'))
