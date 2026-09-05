import json
import logging
import base64
import io
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

def _normalize_phone(phone_str):
    if not phone_str:
        return ''
    digits = re.sub(r'\D', '', str(phone_str))
    if len(digits) > 10 and digits.startswith('1'):
        digits = digits[-10:]
    return digits

def _build_empleado_phone_map(env):
    emp_map = {}
    emps = env['flota.empleado'].with_context(active_test=False).search([])
    for emp in emps:
        if not emp.numero_flota:
            continue
        norm = _normalize_phone(emp.numero_flota)
        if norm:
            emp_map[norm] = emp
            if len(norm) >= 10:
                emp_map[norm[-10:]] = emp
            if len(norm) >= 7:
                emp_map[norm[-7:]] = emp
    return emp_map


class FlotaFacturaConciliacion(models.Model):
    _name = 'flota.factura.conciliacion'
    _description = 'Conciliación Financiera de Factura de Flota'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'periodo desc, id desc'

    name = fields.Char(string='Referencia / Folio', required=True, copy=False, default=lambda self: _('Nuevo'), index=True, tracking=True)
    proveedor = fields.Char(string='Proveedor', default='Claro Dominicana', required=True, tracking=True)
    periodo = fields.Char(string='Periodo / Mes (AAAA-MM)', required=True, default=lambda self: fields.Date.today().strftime('%Y-%m'), index=True, tracking=True)
    fecha_factura = fields.Date(string='Fecha', default=fields.Date.context_today, required=True, tracking=True)
    
    archivo_pdf = fields.Binary(string='Adjuntar PDF Factura Claro', attachment=True)
    pdf_filename = fields.Char(string='Nombre del Archivo PDF')

    renta_mensual = fields.Monetary(string='Renta Mensual', currency_field='currency_id', default=0.0, tracking=True)
    renta_otros_servicios = fields.Monetary(string='Renta Otros Servicios', currency_field='currency_id', default=0.0, tracking=True)
    uso_data_movil = fields.Monetary(string='Uso Data Móvil', currency_field='currency_id', default=0.0, tracking=True)
    llamadas_roaming = fields.Monetary(string='Llamadas Roaming', currency_field='currency_id', default=0.0, tracking=True)
    otros_cargos_creditos = fields.Monetary(string='Otros Cargos / Créditos (CR)', currency_field='currency_id', default=0.0, tracking=True, help="Monto de descuentos o notas de crédito")

    subtotal = fields.Monetary(string='Subtotal Factura', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)
    itbis_monto = fields.Monetary(string='ITBIS (18%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)
    cdt_monto = fields.Monetary(string='CDT (2%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)
    isc_monto = fields.Monetary(string='ISC (10%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)
    total_mes = fields.Monetary(string='Total del Mes', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True)

    currency_id = fields.Many2one('res.currency', string='Moneda', default=lambda self: self.env.company.currency_id)
    estado = fields.Selection([
        ('draft', 'Borrador'),
        ('procesando', 'Procesando'),
        ('conciliado', 'Conciliado'),
        ('error', 'Con Errores / Desviaciones')
    ], string='Estado', default='draft', required=True, index=True, tracking=True)

    notes = fields.Text(string='Observaciones y Notas')

    linea_ids = fields.One2many('flota.factura.linea', 'conciliacion_id', string='Desglose por Empleado / Número')
    resumen_depto_ids = fields.One2many('flota.factura.departamento.resumen', 'conciliacion_id', string='Resumen por Departamento')

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
        """ Agrupa y consolida el gasto por Departamento, impacta historial y sincroniza estado (Activo/Inactivo) de Empleados """
        for rec in self:
            rec.resumen_depto_ids.unlink()
            dept_totals = {}
            seen_emp_ids = set()
            seen_phones = set()

            for linea in rec.linea_ids:
                if linea.numero_flota:
                    norm = _normalize_phone(linea.numero_flota)
                    if norm:
                        seen_phones.add(norm)
                        if len(norm) >= 10:
                            seen_phones.add(norm[-10:])
                        if len(norm) >= 7:
                            seen_phones.add(norm[-7:])

                if linea.empleado_id:
                    seen_emp_ids.add(linea.empleado_id.id)
                    linea.empleado_id.write({
                        'ultima_facturacion_monto': linea.total_linea,
                        'ultima_facturacion_periodo': str(rec.periodo or ''),
                    })

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

            # Sincronización automática de estado de Empleados (Activo vs Inactivo)
            all_emps = self.env['flota.empleado'].with_context(active_test=False).search([])
            for emp in all_emps:
                if not emp.numero_flota:
                    continue
                emp_norm = _normalize_phone(emp.numero_flota)
                if not emp_norm:
                    continue

                is_present = (
                    emp.id in seen_emp_ids or
                    emp_norm in seen_phones or
                    (len(emp_norm) >= 10 and emp_norm[-10:] in seen_phones) or
                    (len(emp_norm) >= 7 and emp_norm[-7:] in seen_phones)
                )

                if is_present:
                    if emp.estado != 'active':
                        emp.write({'estado': 'active'})
                        emp.message_post(body=_("Estado del empleado actualizado a <b>Activo</b> al ser detectado en la conciliación de Claro (%s).") % rec.periodo)
                else:
                    if emp.estado != 'inactive':
                        emp.write({'estado': 'inactive'})
                        emp.message_post(body=_("Estado del empleado actualizado automáticamente a <b>Inactivo</b> por NO figurar en la factura de Claro (%s).") % rec.periodo)

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
                
                if data['departamento_id']:
                    dept_rec = self.env['flota.departamento'].browse(data['departamento_id'])
                    if dept_rec.exists():
                        new_vals = {
                            'ultima_facturacion_monto': data['monto_total'],
                            'ultima_facturacion_periodo': str(rec.periodo or '')
                        }
                        if dept_rec.ultima_facturacion_periodo and dept_rec.ultima_facturacion_periodo != str(rec.periodo or ''):
                            new_vals['penultima_facturacion_monto'] = dept_rec.ultima_facturacion_monto
                            new_vals['penultima_facturacion_periodo'] = dept_rec.ultima_facturacion_periodo
                        dept_rec.write(new_vals)

            rec.write({'resumen_depto_ids': resumen_vals})

    def action_marcar_conciliado(self):
        self.ensure_one()
        self.action_generar_resumen_departamentos()
        self.write({'estado': 'conciliado'})
        self.message_post(body=_("Factura de Flota marcada como Conciliada correctamente."))

    def _extract_pdf_text_native(self, pdf_bytes):
        text = ""
        try:
            import io
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
        except Exception as e:
            _logger.warning("Error extrayendo con pdfplumber: %s", str(e))

        if not text or len(text.strip()) < 50:
            try:
                import io
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(io.BytesIO(pdf_bytes))
                    for page in reader.pages:
                        text += (page.extract_text() or "") + "\n"
                except Exception:
                    from PyPDF2 import PdfFileReader
                    reader = PdfFileReader(io.BytesIO(pdf_bytes))
                    for i in range(reader.getNumPages()):
                        text += (reader.getPage(i).extractText() or "") + "\n"
            except Exception as e2:
                _logger.error("Error extrayendo con PyPDF/PyPDF2: %s", str(e2))
                
        return text

    def action_procesar_pdf_nativo(self):
        """ Extrae y concilia la factura PDF directamente en Odoo """
        self.ensure_one()
        if not self.archivo_pdf:
            raise UserError(_('Por favor adjunte el archivo PDF de la Factura de Claro antes de procesar.'))

        pdf_bytes = base64.b64decode(self.archivo_pdf)
        pdf_text = self._extract_pdf_text_native(pdf_bytes)

        if not pdf_text or len(pdf_text.strip()) < 20:
            raise UserError(_('No se pudo extraer texto del archivo PDF adjunto.'))

        renta_m = 0.0
        renta_o = 0.0
        data_m = 0.0
        roam_m = 0.0
        cred_m = 0.0

        m_renta = re.search(r'Renta\s+mensual\s+([0-9,]+\.[0-9]{2})', pdf_text, re.IGNORECASE)
        if m_renta:
            renta_m = float(m_renta.group(1).replace(',', ''))

        m_renta_o = re.search(r'Renta\s+otros\s+servicios\s+([0-9,]+\.[0-9]{2})', pdf_text, re.IGNORECASE)
        if m_renta_o:
            renta_o = float(m_renta_o.group(1).replace(',', ''))

        m_data = re.search(r'Uso\s+servicios\s+Data\s+M[oó]vil\s+([0-9,]+\.[0-9]{2})', pdf_text, re.IGNORECASE)
        if m_data:
            data_m = float(m_data.group(1).replace(',', ''))

        m_roam = re.search(r'Llamadas\s+Roaming\s+([0-9,]+\.[0-9]{2})', pdf_text, re.IGNORECASE)
        if m_roam:
            roam_m = float(m_roam.group(1).replace(',', ''))

        m_cred = re.search(r'Otros\s+cargos,?\s+cr[eé]ditos.*?([0-9,]+\.[0-9]{2}\s*(?:CR)?)', pdf_text, re.IGNORECASE)
        if m_cred:
            t_c = m_cred.group(1).upper()
            val = float(re.sub(r'[^0-9.]', '', t_c.replace(',', '')) or 0)
            cred_m = -val if ('CR' in t_c or '-' in t_c) else val

        emp_map = _build_empleado_phone_map(self.env)
        lineas_vals = []
        lines = pdf_text.split('\n')
        seen_phones = set()

        for line_str in lines:
            m_phone = re.search(r'(?:1[\s-]?)?\(?(8[0249]\d)\)?[\s-]?(\d{3})[\s-]?(\d{4})', line_str)
            if not m_phone:
                continue

            raw_phone = m_phone.group(0)
            clean_phone = _normalize_phone(raw_phone)
            if not (clean_phone.startswith(('809', '829', '849')) and len(clean_phone) == 10):
                continue
            if clean_phone in ('8092201212', '8092201111'):
                continue

            if clean_phone in seen_phones:
                continue
            seen_phones.add(clean_phone)

            tokens = line_str.split()
            num_values = []
            for tok in tokens:
                m_val = re.search(r'(-?\s*[0-9,]+\.[0-9]{2}\s*(?:CR)?)', tok, re.IGNORECASE)
                if m_val:
                    t_str = m_val.group(1).upper()
                    is_cr = 'CR' in t_str or '-' in t_str
                    v = float(re.sub(r'[^0-9.]', '', t_str.replace(',', '')) or 0)
                    if is_cr:
                        v = -abs(v)
                    num_values.append(v)

            r_plan = 0.0
            r_otros = 0.0
            uso_add = 0.0
            roam = 0.0
            finan = 0.0
            cred = 0.0

            if len(num_values) >= 7:
                r_plan = num_values[0]
                r_otros = num_values[1]
                uso_add = num_values[2]
                roam = num_values[3]
                if len(num_values) > 4:
                    if num_values[4] < 0:
                        cred = num_values[4]
                    else:
                        finan = num_values[4]
            elif len(num_values) >= 5:
                r_plan = num_values[0]
                uso_add = num_values[1]
                roam = num_values[2]
                if num_values[3] < 0:
                    cred = num_values[3]
                else:
                    finan = num_values[3]
            elif len(num_values) >= 1:
                r_plan = num_values[0]

            emp = emp_map.get(clean_phone) or emp_map.get(clean_phone[-10:]) or (emp_map.get(clean_phone[-7:]) if len(clean_phone) >= 7 else None)

            lineas_vals.append({
                'conciliacion_id': self.id,
                'numero_flota': clean_phone,
                'empleado_id': emp.id if emp else False,
                'monto_renta_plan': r_plan,
                'monto_otros_servicios': r_otros,
                'monto_uso_adicional': uso_add,
                'monto_roaming': roam,
                'monto_financiamiento': finan,
                'monto_creditos': cred,
            })

        self.write({
            'renta_mensual': renta_m,
            'renta_otros_servicios': renta_o,
            'uso_data_movil': data_m,
            'llamadas_roaming': roam_m,
            'otros_cargos_creditos': cred_m,
            'estado': 'procesando'
        })

        self.linea_ids.unlink()
        if lineas_vals:
            self.env['flota.factura.linea'].create(lineas_vals)

        self.action_generar_resumen_departamentos()
        self.write({'estado': 'conciliado'})

        self.message_post(body=_("<b>Factura PDF procesada NATIVAMENTE en Odoo:</b><br/>Líneas encontradas: %s | Gran Total: RD$%s") % (len(seen_phones), self.total_mes))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Extracción y Conciliación Exitosa'),
                'message': _('Se procesó la factura PDF nativamente. Se extrajeron %s líneas telefónicas.') % len(seen_phones),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'}
            }
        }

    def action_exportar_excel(self):
        """ Exporta la Conciliación Completa a una ÚNICA HOJA de Excel (.xlsx) """
        self.ensure_one()
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Conciliación Factura Claro"
        
        header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        title_font = Font(name="Calibri", size=14, bold=True, color="1F2937")
        bold_font = Font(name="Calibri", size=11, bold=True)
        summary_title_fill = PatternFill(start_color="374151", end_color="374151", fill_type="solid")
        total_fill = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")

        ws["A1"] = f"CONCILIACIÓN FINANCIERA FACTURA CLARO — {self.name}"
        ws["A1"].font = title_font
        ws["A2"] = f"Periodo: {self.periodo} | Fecha: {self.fecha_factura} | Estado: {self.estado.upper()}"
        ws["A2"].font = Font(italic=True, color="4B5563")

        # Columnas exactas en el mismo orden que en la vista: EMPLEADO, NÚMERO FLOTA, CARGO, DEPARTAMENTO, TOTAL LÍNEA
        headers_emp = ["EMPLEADO", "NÚMERO FLOTA", "CARGO", "DEPARTAMENTO", "TOTAL LÍNEA (RD$)"]
        for col_num, h in enumerate(headers_emp, 1):
            cell = ws.cell(row=4, column=col_num, value=h)
            cell.fill = header_fill
            cell.font = header_font

        current_row = 5
        for l in self.linea_ids:
            ws.cell(row=current_row, column=1, value=l.empleado_id.name if l.empleado_id else 'NO REGISTRADO')
            ws.cell(row=current_row, column=2, value=l.numero_flota)
            ws.cell(row=current_row, column=3, value=l.cargo or '')
            ws.cell(row=current_row, column=4, value=l.departamento_id.name if l.departamento_id else 'N/A')
            c_tot = ws.cell(row=current_row, column=5, value=l.total_linea)
            c_tot.number_format = '"RD$"#,##0.00'
            current_row += 1

        current_row += 2

        ws.cell(row=current_row, column=1, value="RESUMEN GENERAL Y TRIBUTACIÓN FACTURA CLARO").font = bold_font
        ws.cell(row=current_row, column=1).fill = summary_title_fill
        ws.cell(row=current_row, column=1).font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        ws.cell(row=current_row, column=2, value="MONTO (RD$)").fill = summary_title_fill
        ws.cell(row=current_row, column=2).font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        current_row += 1

        rubros = [
            ("Renta Mensual", self.renta_mensual),
            ("Renta Otros Servicios", self.renta_otros_servicios),
            ("Uso Servicios Data Móvil", self.uso_data_movil),
            ("Llamadas Roaming", self.llamadas_roaming),
            ("Otros Cargos, Créditos o Descuentos (CR)", self.otros_cargos_creditos),
            ("SUBTOTAL", self.subtotal),
            ("ITBIS - 18%", self.itbis_monto),
            ("CDT - 2%", self.cdt_monto),
            ("ISC - 10%", self.isc_monto),
            ("TOTAL DEL MES", self.total_mes)
        ]

        for name, val in rubros:
            c_name = ws.cell(row=current_row, column=1, value=name)
            c_val = ws.cell(row=current_row, column=2, value=val)
            c_val.number_format = '"RD$"#,##0.00'
            
            if name in ["SUBTOTAL", "TOTAL DEL MES"]:
                c_name.font = bold_font
                c_val.font = bold_font
            if name == "TOTAL DEL MES":
                c_name.fill = total_fill
                c_val.fill = total_fill

            current_row += 1

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 14)

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
    periodo = fields.Char(string='Periodo', related='conciliacion_id.periodo', store=True, readonly=True)
    fecha_factura = fields.Date(string='Fecha', related='conciliacion_id.fecha_factura', store=True, readonly=True)
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
        emp_map = _build_empleado_phone_map(self.env)
        for vals in vals_list:
            if not vals.get('empleado_id') and vals.get('numero_flota'):
                norm = _normalize_phone(vals['numero_flota'])
                emp = emp_map.get(norm) or emp_map.get(norm[-10:])
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
