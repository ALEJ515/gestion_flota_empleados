import logging


_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        UPDATE flota_empleado
           SET estado_asignacion = 'disponible',
               name = NULL,
               cargo = NULL,
               subdepartamento_id = NULL,
               ruta_id = NULL
         WHERE name ~* '^disponible([[:space:]]+[0-9]+)?$'
           AND COALESCE(numero_flota, '') <> ''
           AND NOT EXISTS (
               SELECT 1
                 FROM flota_entrega_equipo acta
                WHERE acta.empleado_id = flota_empleado.id
           )
    """)
    _logger.info(
        "Migrated %s legacy placeholder employee records to available phone lines.",
        cr.rowcount,
    )
