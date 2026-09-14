# -*- coding: utf-8 -*-
"""
Migración: introduce el campo `origen_linea` en flota.factura.linea.

Al crear el campo nuevo, Odoo aplica automáticamente su `default='manual'`
a TODAS las filas ya existentes en la base de datos (comportamiento estándar
de `_auto_init` al agregar una columna con default). Sin embargo, hasta esta
versión el módulo NO tenía la funcionalidad de "agregar empleado manualmente":
absolutamente todas las líneas registradas hasta ahora provienen de la
extracción automática del PDF de Claro.

Este script corrige ese default incorrecto marcando como 'pdf' todas las
líneas que ya existían antes de esta versión, para que:
  - No se pierdan datos de facturas antiguas al mostrarlas con el nuevo badge.
  - Al volver a extraer el PDF de una factura antigua, esas líneas se sigan
    reemplazando correctamente (el nuevo filtro de `unlink()` solo borra
    líneas marcadas como 'pdf').
"""


def migrate(cr, version):
    if not version:
        # Instalación nueva, no upgrade: no hay datos previos que corregir.
        return
    cr.execute("""
        UPDATE flota_factura_linea
        SET origen_linea = 'pdf'
        WHERE origen_linea IS NULL OR origen_linea = 'manual'
    """)
