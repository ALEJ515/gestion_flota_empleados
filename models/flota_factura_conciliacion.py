import json
import logging
import base64
import io
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class FlotaFacturaConciliacion(models.Model):
    _name = 'flota.factura.conciliacion'
    _description = 'Conciliación Financiera de Factura de Flota'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'periodo desc, id desc'

    name = fields.Char(string='Referencia / Folio', required=True, copy=False, default=lambda self: _('Nuevo'), index=True, tracking=True)
    proveedor = fields.Char(string='Proveedor Telecom', default='Claro Dominicana', required=True, tracking=True)
    periodo = fields.Char(string='Periodo / Mes (AAAA-MM)', required=True, index=True, tracking=True)
    fecha_factura = fields.Date(string='Fecha de Factura', default=fields.Date.context_today, required=True, tracking=True)
    
    # Archivo PDF Adjunto
    archivo_pdf = fields.Binary(string='Adjuntar PDF Factura Claro', attachment=True)
    pdf_filename = fields.Char(string='Nombre del Archivo PDF')

    # --- DATOS GENERALES FACTURA CLARO ---
    renta_mensual = fields.Monetary(string='Renta Mensual', currency_field='currency_id', default=0.0, tracking=True)
    renta_otros_servicios = fields.Monetary(string='Renta Otros Servicios', currency_field='currency_id', default=0.0, tracking=True)
    uso_data_movil = fields.Monetary(string='Uso Data Móvil', currency_field='currency_id', default=0.0, tracking=True)
    llamadas_roaming = fields.Monetary(string='Llamadas Roaming', currency_field='currency_id', default=0.0, tracking=True)
    otros_cargos_creditos = fields.Monetary(string='Otros Cargos / Créditos (CR)', currency_field='currency_id', default=0.0, tracking=True, help="Monto de descuentos o notas de crédito (monto negativo o positivo ajustado)")

    # --- DATOS COMPUTADOS AUTOMÁTICAMENTE ---
    subtotal = fields.Monetary(string='Subtotal Factura', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)
    itbis_monto = fields.Monetary(string='ITBIS (18%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)
    cdt_monto = fields.Monetary(string='CDT (2%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)
    isc_monto = fields.Monetary(string='ISC (10%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)
    total_mes = fields.Monetary(string='Total del Mes', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)

    currency_id = fields.Many2one('res.currency', string='Moneda', default=lambda self: self.env.company.currency_id)
    estado = fields.Selection([
        ('draft', 'Borrador'),
        ('procesando', 'Procesando n8n'),
        ('conciliado', 'Conciliado'),
        ('error', 'Con Errores / Desviaciones')
    ], string='Estado', default='draft', required=True, index=True, tracking=True)

    notes = fields.Text(string='Observaciones y Notas')

    # Relaciones
    linea_ids = fields.One2many('flota.factura.linea', 'conciliacion_id', string='Desglose por Empleado / Número')
    resumen_depto_ids = fields.One2many('flota.factura.departamento.resumen', 'conciliacion_id', string='Resumen por Departamento')

    # KPIs Computados
    count_lineas = fields.Integer(string='Total Líneas', compute='_compute_kpis', store=True)
    count_excesos = fields.Integer(string='Líneas con Exceso', compute='_compute_kpis', store=True)
    monto_excesos = fields.Monetary(string='Monto Total Excesos', compute='_compute_kpis', store=True, currency_field='currency_id')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('flota.factura.conciliacion') or _('FAC-CLARO-%s') % fields.Date.today()
        return super(FlotaFacturaConciliacion, self).create(vals_list)

    @api.depends('renta_mensual', 'renta_otros_servicios', 'uso_data_movil', 'llamadas_roaming', 'otros_cargos_creditos')
    def _compute_totales_factura(self):
        for rec in self:
            sub = rec.renta_mensual + rec.renta_otros_servicios + rec.uso_data_movil + rec.llamadas_roaming + rec.otros_cargos_creditos
            rec.subtotal = sub
            rec.itbis_monto = sub * 0.18
            rec.cdt_monto = sub * 0.02
            rec.isc_monto = sub * 0.10
            rec.total_mes = sub + rec.itbis_monto + rec.cdt_monto + rec.isc_monto

    @api.depends('linea_ids', 'linea_ids.estado_linea', 'linea_ids.monto_uso_adicional', 'linea_ids.monto_roaming')
    def _compute_kpis(self):
        for rec in self:
            rec.count_lineas = len(rec.linea_ids)
            excesos = rec.linea_ids.filtered(lambda l: l.estado_linea in ['exceso_data', 'exceso_roaming'])
            rec.count_excesos = len(excesos)
            rec.monto_excesos = sum(excesos.mapped(lambda l: l.monto_uso_adicional + l.monto_roaming))

    def action_generar_resumen_departamentos(self):
        """ Agrupa y consolida el gasto por Departamento / CEDI """
        for rec in self:
            rec.resumen_depto_ids.unlink()
            dept_totals = {}
            for linea in rec.linea_ids:
                dept_id = linea.departamento_id.id if linea.departamento_id else 0
                
                if dept_id not in dept_totals:
                    dept_totals[dept_id] = {
                        'departamento_id': linea.departamento_id.id if linea.departamento_id else False,
                        'ubicacion_id': linea.ubicacion_id.id if linea.ubicacion_id else False,
                        'cantidad_empleados': 0,
                        'monto_subtotal': 0.0,
                        'monto_total': 0.0
                    }
                dept_totals[dept_id]['cantidad_empleados'] += 1
                dept_totals[dept_id]['monto_subtotal'] += linea.subtotal_linea
                dept_totals[dept_id]['monto_total'] += linea.total_linea

            resumen_vals = []
            tot_gral = rec.total_mes if rec.total_mes else 1.0
            for d_id, data in dept_totals.items():
                pct = (data['monto_total'] / tot_gral) * 100.0
                resumen_vals.append((0, 0, {
                    'conciliacion_id': rec.id,
                    'departamento_id': data['departamento_id'],
                    'ubicacion_id': data['ubicacion_id'],
                    'cantidad_empleados': data['cantidad_empleados'],
                    'monto_subtotal': data['monto_subtotal'],
                    'monto_total': data['monto_total'],
                    'porcentaje_gasto': pct
                }))
            rec.write({'resumen_depto_ids': resumen_vals})

    def action_marcar_conciliado(self):
        self.ensure_one()
        self.action_generar_resumen_departamentos()
        self.write({'estado': 'conciliado'})
        self.message_post(body=_("Factura de Flota marcada como <b>Conciliada</b> correctamente."))

    def action_procesar_pdf_n8n(self):
        """ Envía el archivo PDF adjunto al Webhook de n8n para parsing y conciliación """
        self.ensure_one()
        if not self.archivo_pdf:
            raise UserError(_('Por favor adjunte un archivo PDF de la Factura Claro antes de presionar este botón.'))
        
        import requests
        ICP = self.env['ir.config_parameter'].sudo()
        n8n_webhook_url = ICP.get_param('gestion_flota_empleados.n8n_webhook_url', 'http://100.95.106.4:5678/webhook/conciliar-factura-claro')
        
        pdf_bytes = base64.b64decode(self.archivo_pdf)
        files = {
            'file': (self.pdf_filename or 'factura_claro.pdf', pdf_bytes, 'application/pdf')
        }
        data = {
            'periodo': self.periodo,
            'proveedor': self.proveedor or 'Claro Dominicana'
        }

        try:
            response = requests.post(n8n_webhook_url, files=files, data=data, timeout=30)
            if response.status_code in [200, 201]:
                res_data = response.json()
                if isinstance(res_data, dict) and res_data.get('status') == 'success':
                    self.message_post(body=_("<b>Factura PDF procesada con éxito via n8n:</b><br/>Total: RD$%s | Líneas: %s") % (res_data.get('total_mes'), res_data.get('total_lineas')))
                    return {
                        'type': 'ir.actions.client',
                        'tag': 'display_notification',
                        'params': {
                            'title': _('Factura PDF Procesada'),
                            'message': _('La factura PDF fue enviada y conciliada exitosamente.'),
                            'type': 'success',
                            'next': {'type': 'ir.actions.client', 'tag': 'reload'}
                        }
                    }
        except Exception as e:
            _logger.error("Error enviando PDF a n8n: %s", str(e))
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Enviado a n8n'),
                'message': _('El PDF se envió a n8n para su lectura y concatenación.'),
                'type': 'info',
                'next': {'type': 'ir.actions.client', 'tag': 'reload'}
            }
        }

    def action_exportar_excel(self):
        """ Exporta la Conciliación Completa a un libro formateado de Excel (.xlsx) """
        self.ensure_one()
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        wb = openpyxl.Workbook()
        ws1 = wb.active
        ws1.title = "Resumen Factura Claro"
        
        header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        title_font = Font(name="Calibri", size=14, bold=True, color="1F2937")
        bold_font = Font(name="Calibri", size=11, bold=True)

        ws1["A1"] = f"CONCILIACIÓN FINANCIERA FACTURA CLARO — {self.name}"
        ws1["A1"].font = title_font
        ws1["A2"] = f"Periodo: {self.periodo} | Fecha: {self.fecha_factura} | Estado: {self.estado.upper()}"
        ws1["A2"].font = Font(italic=True, color="4B5563")

        ws1["A4"] = "RUBRO FACTURA CLARO"
        ws1["B4"] = "MONTO (RD$)"
        ws1["A4"].fill = header_fill
        ws1["A4"].font = header_font
        ws1["B4"].fill = header_fill
        ws1["B4"].font = header_font

        rubros = [
            ("Renta Mensual", self.renta_mensual),
            ("Renta Otros Servicios", self.renta_otros_servicios),
            ("Uso Data Móvil", self.uso_data_movil),
            ("Llamadas Roaming", self.llamadas_roaming),
            ("Otros Cargos / Créditos (CR)", self.otros_cargos_creditos),
            ("SUBTOTAL", self.subtotal),
            ("ITBIS (18%)", self.itbis_monto),
            ("CDT (2%)", self.cdt_monto),
            ("ISC (10%)", self.isc_monto),
            ("TOTAL DEL MES", self.total_mes)
        ]

        row = 5
        for name, val in rubros:
            ws1.cell(row=row, column=1, value=name)
            cell_val = ws1.cell(row=row, column=2, value=val)
            cell_val.number_format = '"RD$"#,##0.00'
            if name in ["SUBTOTAL", "TOTAL DEL MES"]:
                ws1.cell(row=row, column=1).font = bold_font
                cell_val.font = bold_font
            row += 1

        # Sheet 2: Consolidado por Departamento
        ws2 = wb.create_sheet(title="Consolidado Departamento")
        ws2["A1"] = f"RESUMEN GASTO POR DEPARTAMENTO Y CEDI — {self.name}"
        ws2["A1"].font = title_font
        
        headers_depto = ["DEPARTAMENTO", "CEDI / UBICACIÓN", "EMPLEADOS", "SUBTOTAL (RD$)", "TOTAL (RD$)", "% DEL GASTO"]
        for col_num, h in enumerate(headers_depto, 1):
            cell = ws2.cell(row=3, column=col_num, value=h)
            cell.fill = header_fill
            cell.font = header_font

        row = 4
        for d in self.resumen_depto_ids:
            ws2.cell(row=row, column=1, value=d.departamento_id.name if d.departamento_id else 'N/A')
            ws2.cell(row=row, column=2, value=d.ubicacion_id.name if d.ubicacion_id else 'N/A')
            ws2.cell(row=row, column=3, value=d.cantidad_empleados)
            c4 = ws2.cell(row=row, column=4, value=d.monto_subtotal)
            c4.number_format = '"RD$"#,##0.00'
            c5 = ws2.cell(row=row, column=5, value=d.monto_total)
            c5.number_format = '"RD$"#,##0.00'
            c6 = ws2.cell(row=row, column=6, value=d.porcentaje_gasto / 100.0)
            c6.number_format = '0.00%'
            row += 1

        # Sheet 3: Detalle por Empleado
        ws3 = wb.create_sheet(title="Detalle Empleados")
        ws3["A1"] = f"DESGLOSE LÍNEA POR EMPLEADO — {self.name}"
        ws3["A1"].font = title_font

        headers_emp = ["NÚMERO FLOTA", "EMPLEADO", "DEPARTAMENTO", "CEDI / UBICACIÓN", "CARGO", "RENTA PLAN", "USO ADICIONAL", "ROAMING", "SUBTOTAL", "TOTAL LÍNEA", "ESTADO"]
        for col_num, h in enumerate(headers_emp, 1):
            cell = ws3.cell(row=3, column=col_num, value=h)
            cell.fill = header_fill
            cell.font = header_font

        row = 4
        for l in self.linea_ids:
            ws3.cell(row=row, column=1, value=l.numero_flota)
            ws3.cell(row=row, column=2, value=l.empleado_id.name if l.empleado_id else 'NO REGISTRADO')
            ws3.cell(row=row, column=3, value=l.departamento_id.name if l.departamento_id else 'N/A')
            ws3.cell(row=row, column=4, value=l.ubicacion_id.name if l.ubicacion_id else 'N/A')
            ws3.cell(row=row, column=5, value=l.cargo or '')
            c_renta = ws3.cell(row=row, column=6, value=l.monto_renta_plan)
            c_renta.number_format = '"RD$"#,##0.00'
            c_uso = ws3.cell(row=row, column=7, value=l.monto_uso_adicional)
            c_uso.number_format = '"RD$"#,##0.00'
            c_roam = ws3.cell(row=row, column=8, value=l.monto_roaming)
            c_roam.number_format = '"RD$"#,##0.00'
            c_sub = ws3.cell(row=row, column=9, value=l.subtotal_linea)
            c_sub.number_format = '"RD$"#,##0.00'
            c_tot = ws3.cell(row=row, column=10, value=l.total_linea)
            c_tot.number_format = '"RD$"#,##0.00'
            ws3.cell(row=row, column=11, value=l.estado_linea.upper())
            row += 1

        for ws in [ws1, ws2, ws3]:
            for col in ws.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = openpyxl.utils.get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        file_data = base64.b64encode(output.read())
        output.close()

        attachment = self.env['ir.attachment'].create({
            'name': f'Conciliacion_Claro_{self.periodo}_{self.name}.xlsx',
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


class FlotaFacturaLinea(models.Model):
    _name = 'flota.factura.linea'
    _description = 'Detalle de Factura por Línea / Empleado'
    _order = 'total_linea desc, id asc'

    conciliacion_id = fields.Many2one('flota.factura.conciliacion', string='Factura Conciliación', ondelete='cascade', index=True)
    numero_flota = fields.Char(string='Número Flota', required=True, index=True)
    
    empleado_id = fields.Many2one('flota.empleado', string='Empleado', ondelete='set null', index=True)
    departamento_id = fields.Many2one('flota.departamento', string='Departamento', related='empleado_id.departamento_id', store=True, readonly=True)
    ubicacion_id = fields.Many2one('flota.ubicacion', string='CEDI / Ubicación', related='empleado_id.ubicacion_id', store=True, readonly=True)
    cargo = fields.Char(string='Cargo', related='empleado_id.cargo', readonly=True)

    monto_renta_plan = fields.Monetary(string='Renta Plan', currency_field='currency_id', default=0.0)
    monto_otros_servicios = fields.Monetary(string='Otros Servicios', currency_field='currency_id', default=0.0)
    monto_uso_adicional = fields.Monetary(string='Uso Data/Voz Adicional', currency_field='currency_id', default=0.0)
    monto_roaming = fields.Monetary(string='Roaming / LD', currency_field='currency_id', default=0.0)
    monto_financiamiento = fields.Monetary(string='Financiamiento Equipo', currency_field='currency_id', default=0.0)
    monto_creditos = fields.Monetary(string='Créditos / Ajustes', currency_field='currency_id', default=0.0)

    subtotal_linea = fields.Monetary(string='Subtotal Línea', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    itbis_linea = fields.Monetary(string='ITBIS (18%)', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    cdt_linea = fields.Monetary(string='CDT (2%)', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    isc_linea = fields.Monetary(string='ISC (10%)', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    total_linea = fields.Monetary(string='Total Línea (RD$)', compute='_compute_linea_totals', store=True, currency_field='currency_id')

    currency_id = fields.Many2one('res.currency', string='Moneda', related='conciliacion_id.currency_id', store=True)

    estado_linea = fields.Selection([
        ('ok', 'Normal'),
        ('exceso_data', 'Exceso Data'),
        ('exceso_roaming', 'Exceso Roaming'),
        ('desconocido', 'Número No Registrado')
    ], string='Estado Línea', compute='_compute_estado_linea', store=True, default='ok')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('empleado_id') and vals.get('numero_flota'):
                num_clean = vals['numero_flota'].replace('-', '').replace(' ', '').replace('+', '')
                emp = self.env['flota.empleado'].search([
                    '|',
                    ('numero_flota', '=', vals['numero_flota']),
                    ('numero_flota', '=', num_clean)
                ], limit=1)
                if emp:
                    vals['empleado_id'] = emp.id
        return super(FlotaFacturaLinea, self).create(vals_list)

    @api.depends('monto_renta_plan', 'monto_otros_servicios', 'monto_uso_adicional', 'monto_roaming', 'monto_financiamiento', 'monto_creditos')
    def _compute_linea_totals(self):
        for rec in self:
            sub = rec.monto_renta_plan + rec.monto_otros_servicios + rec.monto_uso_adicional + rec.monto_roaming + rec.monto_financiamiento + rec.monto_creditos
            rec.subtotal_linea = sub
            rec.itbis_linea = sub * 0.18
            rec.cdt_linea = sub * 0.02
            rec.isc_linea = sub * 0.10
            rec.total_linea = sub + rec.itbis_linea + rec.cdt_linea + rec.isc_linea

    @api.depends('empleado_id', 'monto_uso_adicional', 'monto_roaming')
    def _compute_estado_linea(self):
        for rec in self:
            if not rec.empleado_id:
                rec.estado_linea = 'desconocido'
            elif rec.monto_roaming > 0:
                rec.estado_linea = 'exceso_roaming'
            elif rec.monto_uso_adicional > 0:
                rec.estado_linea = 'exceso_data'
            else:
                rec.estado_linea = 'ok'


class FlotaFacturaDepartamentoResumen(models.Model):
    _name = 'flota.factura.departamento.resumen'
    _description = 'Resumen Consolidado de Factura por Departamento'
    _order = 'monto_total desc'

    conciliacion_id = fields.Many2one('flota.factura.conciliacion', string='Factura Conciliación', ondelete='cascade', index=True)
    departamento_id = fields.Many2one('flota.departamento', string='Departamento')
    ubicacion_id = fields.Many2one('flota.ubicacion', string='CEDI / Ubicación')
    cantidad_empleados = fields.Integer(string='Empleados')
    monto_subtotal = fields.Monetary(string='Subtotal Depto', currency_field='currency_id')
    monto_total = fields.Monetary(string='Total Depto (RD$)', currency_field='currency_id')
    porcentaje_gasto = fields.Float(string='% del Total General', digits=(5, 2))
    currency_id = fields.Many2one('res.currency', string='Moneda', related='conciliacion_id.currency_id')
