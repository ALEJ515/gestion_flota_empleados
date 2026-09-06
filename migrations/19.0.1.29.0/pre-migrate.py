"""Preserve Claro line amounts while adopting semantic field names."""


FIELD_RENAMES = {
    'monto_otros_servicios': 'otros_servicios_datos',
    'monto_uso_adicional': 'uso_local_data_movil',
    'monto_renta_plan': 'llamadas_roaming_otras_llamadas',
    'monto_financiamiento': 'financiamiento_equipos',
    'monto_creditos': 'otros_cargos_descuentos',
    'monto_impuestos_pdf': 'impuestos',
    'total_pdf': 'total',
}


def migrate(cr, version):
    table = 'flota_factura_linea'
    for old_name, new_name in FIELD_RENAMES.items():
        cr.execute(
            """
            SELECT 1
              FROM information_schema.columns
             WHERE table_name = %s
               AND column_name = %s
            """,
            (table, old_name),
        )
        if cr.fetchone():
            cr.execute(
                'ALTER TABLE "%s" RENAME COLUMN "%s" TO "%s"'
                % (table, old_name, new_name)
            )

        cr.execute(
            """
            UPDATE ir_model_fields
               SET name = %s
             WHERE model = 'flota.factura.linea'
               AND name = %s
            """,
            (new_name, old_name),
        )
