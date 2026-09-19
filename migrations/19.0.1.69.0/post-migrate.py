# -*- coding: utf-8 -*-
"""Migración de datos para 19.0.1.69.0.

El campo 'texto_aceptacion' es nuevo. Su 'default' solo se aplica a registros creados
DESPUÉS de la actualización del módulo, por lo que las actas ya existentes quedarían con
este campo vacío y el PDF mostraría la sección "Aceptación y responsabilidad" en blanco.
Aquí se rellena ese campo en todas las actas existentes con el texto legal que antes estaba
fijo (hardcodeado) en el reporte, para no perder contenido en producción.
"""

TEXTO_ACEPTACION_DEFAULT = (
    "Mediante la firma de este documento, comprendo y asumo la responsabilidad que me confiere "
    "la asignación de los equipos aquí detallados y entiendo que la violación a cualquiera de "
    "las directivas establecidas en la Política de Informática, la cual he recibido, leído y "
    "entendido, puede conllevar a que la empresa revoque mis privilegios y tome acciones "
    "disciplinarias y/o legales de acuerdo con lo establecido en dicha política."
)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE flota_entrega_equipo
        SET texto_aceptacion = %s
        WHERE texto_aceptacion IS NULL OR texto_aceptacion = ''
    """, (TEXTO_ACEPTACION_DEFAULT,))
