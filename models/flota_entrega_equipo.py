from urllib.parse import quote as url_quote

from odoo import models, fields, api, _


class FlotaEntregaEquipo(models.Model):
    _name = 'flota.entrega.equipo'
    _description = 'Acta de Recepción y Entrega de Equipos'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'fecha desc, id desc'

    name = fields.Char(
        string='Nº de Acta',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('Nuevo'),
        index=True,
        tracking=True
    )
    empleado_id = fields.Many2one(
        'flota.empleado',
        string='Empleado',
        required=True,
        ondelete='restrict',
        index=True,
        tracking=True,
        help="Empleado al que se le entrega o recibe el equipo. Al seleccionarlo se autocompletan Ruta, Localidad, Teléfono de flota y Responsable."
    )
    fecha = fields.Date(string='Fecha', default=fields.Date.context_today, required=True, tracking=True)
    estado = fields.Selection([
        ('draft', 'Borrador'),
        ('confirmado', 'Confirmado'),
    ], string='Estado', default='draft', required=True, tracking=True, index=True)

    # --- DATOS ENTREGA (autocompletados desde el Empleado, editables) ---
    tipo_asignacion = fields.Selection([
        ('vendedor', 'Vendedor'),
        ('distribuidor', 'Distribuidor'),
        ('otro', 'Otro'),
    ], string='Distribuidor / Vendedor', tracking=True)
    preparado_por_id = fields.Many2one(
        'res.users', string='Preparado por',
        default=lambda self: self.env.user, tracking=True
    )
    ruta_id = fields.Many2one('flota.ruta', string='Ruta', tracking=True)
    ubicacion_id = fields.Many2one('flota.ubicacion', string='Localidad', tracking=True)
    recibido_por = fields.Char(string='Recibido por (Responsable)', tracking=True)
    telefono_flota = fields.Char(string='Núm. de Teléfono (Flota)', tracking=True)

    # --- DATOS FLOTA RECIBIDA POR TI (equipo antiguo devuelto) ---
    equipo_recibido_modelo = fields.Char(string='Modelo (Flota Recibida)')
    equipo_recibido_serial = fields.Char(string='Serial / IMEI (Flota Recibida)')

    # --- DATOS IMPRESORA ---
    impresora_modelo = fields.Char(string='Modelo (Impresora)')
    impresora_serial = fields.Char(string='Serial (Impresora)')

    # --- DATOS DE EQUIPO NUEVO ENTREGADO ---
    linea_ids = fields.One2many(
        'flota.entrega.equipo.linea', 'entrega_id',
        string='Equipos Entregados'
    )
    cantidad_equipos = fields.Integer(string='Cantidad de Equipos', compute='_compute_cantidad_equipos', store=True)

    # --- FIRMAS Y POLÍTICA ---
    entregado_por = fields.Char(string='Entregado por', default=lambda self: self.env.user.name, tracking=True)
    firma_entregado = fields.Binary(string='Firma de quien Entrega', attachment=True)
    firma_recibido = fields.Binary(string='Firma de quien Recibe', attachment=True)
    recibio_politica = fields.Selection([
        ('si', 'Sí'),
        ('no', 'No'),
    ], string='¿Recibió la Política de Informática?', tracking=True)
    politica_url = fields.Char(
        string='Enlace a la Política de Informática',
        default=lambda self: self.env['ir.config_parameter'].sudo().get_param(
            'gestion_flota_empleados.politica_informatica_url', default=''
        ),
        help="URL de la política de informática. Se usa para generar el código QR del acta. "
             "Puede configurarse de forma general en Ajustes Técnicos > Parámetros del Sistema "
             "con la clave 'gestion_flota_empleados.politica_informatica_url'."
    )
    politica_qr_src = fields.Char(string='QR Política (URL interna)', compute='_compute_politica_qr_src')

    # --- CONTROL DOCUMENTAL DEL FORMATO (editable por si cambia la versión oficial) ---
    codigo_formulario = fields.Char(string='Código de Formulario', default='MS-TE-FO-001')
    version_formulario = fields.Char(string='Versión', default='3.00')

    notas = fields.Text(string='Notas')
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company)

    @api.depends('linea_ids.cantidad')
    def _compute_cantidad_equipos(self):
        for rec in self:
            rec.cantidad_equipos = sum(rec.linea_ids.mapped('cantidad'))

    @api.depends('politica_url')
    def _compute_politica_qr_src(self):
        for rec in self:
            if rec.politica_url:
                rec.politica_qr_src = '/report/barcode/QR/%s?width=200&height=200' % url_quote(rec.politica_url, safe='')
            else:
                rec.politica_qr_src = False

    @api.onchange('empleado_id')
    def _onchange_empleado_id(self):
        for rec in self:
            if rec.empleado_id:
                rec.ruta_id = rec.empleado_id.ruta_id
                rec.ubicacion_id = rec.empleado_id.ubicacion_id
                rec.telefono_flota = rec.empleado_id.numero_flota
                rec.recibido_por = rec.empleado_id.name
                if rec.empleado_id.ruta_id and rec.empleado_id.ruta_id.tipo in ('vendedor', 'distribuidor'):
                    rec.tipo_asignacion = rec.empleado_id.ruta_id.tipo
                else:
                    rec.tipo_asignacion = 'otro'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('flota.entrega.equipo') or _('Nuevo')
        return super().create(vals_list)

    def action_confirmar(self):
        self.write({'estado': 'confirmado'})

    def action_restablecer_borrador(self):
        self.write({'estado': 'draft'})

    def action_exportar_excel(self):
        """Exporta el acta de entrega/recepción de equipos a un libro Excel."""
        self.ensure_one()
        import io
        import base64
        import openpyxl
        from openpyxl.styles import Font, PatternFill

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Acta Entrega Equipos"

        header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        title_font = Font(name="Calibri", size=14, bold=True, color="1F2937")
        section_fill = PatternFill(start_color="16A34A", end_color="16A34A", fill_type="solid")
        section_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        bold_font = Font(name="Calibri", size=11, bold=True)

        ws["A1"] = f"ACTA DE RECEPCIÓN Y ENTREGA DE EQUIPOS — {self.name}"
        ws["A1"].font = title_font
        ws["A2"] = f"Código: {self.codigo_formulario} | Versión: {self.version_formulario} | Fecha: {self.fecha}"
        ws["A2"].font = Font(italic=True, color="4B5563")

        row = 4
        ws.cell(row=row, column=1, value="DATOS ENTREGA").font = section_font
        ws.cell(row=row, column=1).fill = section_fill
        ws.cell(row=row, column=2).fill = section_fill
        row += 1
        datos_entrega = [
            ("Distribuidor/Vendedor", dict(self._fields['tipo_asignacion'].selection).get(self.tipo_asignacion, '') if self.tipo_asignacion else ''),
            ("Preparado por", self.preparado_por_id.name or ''),
            ("Ruta", self.ruta_id.name or ''),
            ("Localidad", self.ubicacion_id.name or ''),
            ("Recibido por (responsable)", self.recibido_por or ''),
            ("Núm. de teléfono (flota)", self.telefono_flota or ''),
        ]
        for label, value in datos_entrega:
            ws.cell(row=row, column=1, value=label).font = bold_font
            ws.cell(row=row, column=2, value=value)
            row += 1

        row += 1
        ws.cell(row=row, column=1, value="DATOS FLOTA RECIBIDA POR TI").font = section_font
        ws.cell(row=row, column=1).fill = section_fill
        ws.cell(row=row, column=2).fill = section_fill
        row += 1
        for label, value in [("Modelo", self.equipo_recibido_modelo or 'N/A'), ("Serial/IMEI", self.equipo_recibido_serial or 'N/A')]:
            ws.cell(row=row, column=1, value=label).font = bold_font
            ws.cell(row=row, column=2, value=value)
            row += 1

        row += 1
        ws.cell(row=row, column=1, value="DATOS IMPRESORA").font = section_font
        ws.cell(row=row, column=1).fill = section_fill
        ws.cell(row=row, column=2).fill = section_fill
        row += 1
        for label, value in [("Modelo", self.impresora_modelo or 'N/A'), ("Serial", self.impresora_serial or 'N/A')]:
            ws.cell(row=row, column=1, value=label).font = bold_font
            ws.cell(row=row, column=2, value=value)
            row += 1

        row += 2
        headers_eq = ["TIPO DE EQUIPO", "MARCA", "MODELO", "CANT.", "IMEI / SERIAL", "ESTADO", "OBSERVACIONES"]
        for col_num, h in enumerate(headers_eq, 1):
            cell = ws.cell(row=row, column=col_num, value=h)
            cell.fill = header_fill
            cell.font = header_font
        row += 1
        for line in self.linea_ids:
            ws.cell(row=row, column=1, value=dict(line._fields['tipo_equipo'].selection).get(line.tipo_equipo, ''))
            ws.cell(row=row, column=2, value=line.marca or '')
            ws.cell(row=row, column=3, value=line.modelo or '')
            ws.cell(row=row, column=4, value=line.cantidad)
            ws.cell(row=row, column=5, value=line.imei_serial or '')
            ws.cell(row=row, column=6, value=dict(line._fields['estado_equipo'].selection).get(line.estado_equipo, ''))
            ws.cell(row=row, column=7, value=line.observaciones or '')
            row += 1

        row += 2
        ws.cell(row=row, column=1, value="Entregado por").font = bold_font
        ws.cell(row=row, column=2, value=self.entregado_por or '')
        row += 1
        ws.cell(row=row, column=1, value="Recibió la Política de Informática").font = bold_font
        ws.cell(row=row, column=2, value=dict(self._fields['recibio_politica'].selection).get(self.recibio_politica, ''))

        for col in ws.columns:
            max_len = max((len(str(cell.value or '')) for cell in col), default=0)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 14)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        file_data = base64.b64encode(output.read())
        output.close()

        attachment = self.env['ir.attachment'].create({
            'name': f'{self.name} - {self.empleado_id.name}.xlsx',
            'datas': file_data,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }


class FlotaEntregaEquipoLinea(models.Model):
    _name = 'flota.entrega.equipo.linea'
    _description = 'Línea de Equipo Entregado'
    _order = 'id asc'

    entrega_id = fields.Many2one('flota.entrega.equipo', string='Acta de Entrega', required=True, ondelete='cascade', index=True)
    tipo_equipo = fields.Selection([
        ('celular', 'Celular'),
        ('tablet', 'Tablet'),
        ('laptop', 'Laptop'),
        ('impresora', 'Impresora'),
        ('accesorio', 'Accesorio'),
        ('otro', 'Otro'),
    ], string='Tipo de Equipo', required=True, default='celular')
    marca = fields.Char(string='Marca')
    modelo = fields.Char(string='Modelo')
    cantidad = fields.Integer(string='Cant.', default=1, required=True)
    imei_serial = fields.Char(string='IMEI / Serial')
    estado_equipo = fields.Selection([
        ('nueva', 'Nueva'),
        ('usada', 'Usada'),
    ], string='Estado', default='nueva')
    observaciones = fields.Char(
        string='Estado / Observaciones',
        help="Ej. Protector de pantalla roto, cámara cristal roto, se friza a veces."
    )
