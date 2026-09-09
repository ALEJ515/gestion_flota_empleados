"""Al introducir los grupos de seguridad propios del módulo (Usuario / Administrador),
se asigna el grupo 'Administrador de Flota' a todos los usuarios internos que ya
existían antes de este cambio, para que ninguno pierda el acceso total que ya tenía
(create/write/unlink) sobre los modelos del módulo. El administrador del sistema
puede luego, desde Ajustes > Usuarios, degradar a quien corresponda al grupo
'Usuario de Flota' (sin permiso de eliminar)."""


def migrate(cr, version):
    cr.execute("SELECT res_id FROM ir_model_data WHERE module = 'gestion_flota_empleados' AND name = 'group_flota_manager'")
    row = cr.fetchone()
    if not row:
        return
    group_id = row[0]

    cr.execute("""
        SELECT ru.id FROM res_users ru
        JOIN res_groups_users_rel gu ON gu.uid = ru.id
        JOIN res_groups g ON g.id = gu.gid
        WHERE g.id = (SELECT res_id FROM ir_model_data WHERE module='base' AND name='group_user')
        AND ru.active = true
    """)
    internal_user_ids = [r[0] for r in cr.fetchall()]
    if not internal_user_ids:
        return

    for user_id in internal_user_ids:
        cr.execute(
            "INSERT INTO res_groups_users_rel (gid, uid) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING",
            (group_id, user_id)
        )
