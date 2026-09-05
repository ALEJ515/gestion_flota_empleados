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

def _fix_claro_pdf_line(line_str):
    if not line_str:
        return ''
    fixed = re.sub(r'(\.\d{2}(?:CR)?)(8[0249]\d)', r'\1 \2', line_str, flags=re.IGNORECASE)
    fixed = re.sub(r'(\.\d{2}(?:CR)?)(?=[-\d])', r'\1 ', fixed, flags=re.IGNORECASE)
    return fixed


class FlotaFacturaConciliacion(models.Model):
    _name = 'flota.factura.conciliacion'
    _description = 'Conciliación Financiera de Factura de Flota'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'periodo desc, id desc'

    name = fields.Char(string='Referencia / Folio', required=True, copy=False, default=lambda self: _('Nuevo'), index=True, tracking=True, help="Número de referencia o folio único asignado a la factura de flota.")
    proveedor = fields.Char(string='Proveedor', default='Claro Dominicana', required=True, tracking=True, help="Empresa prestadora del servicio telefónico corporativo (Claro Dominicana).")
    periodo = fields.Char(string='Periodo / Mes (AAAA-MM)', required=True, default=lambda self: fields.Date.today().strftime('%Y-%m'), index=True, tracking=True, help="Año y mes fiscal correspondiente a esta conciliación (Ej. 2026-08).")
    fecha_factura = fields.Date(string='Fecha de Factura', default=fields.Date.context_today, required=True, tracking=True, help="Fecha exacta de emisión o facturación impresa en el documento de Claro.")
    fecha_subida = fields.Datetime(string='Fecha de Subida', default=fields.Datetime.now, readonly=True, help="Fecha y hora de registro y subida del PDF a Odoo.")
    
    archivo_pdf = fields.Binary(string='Adjuntar PDF Factura Claro', attachment=True, help="Documento digital PDF de la factura corporativa Claro para extracción nativa.")
    pdf_filename = fields.Char(string='Nombre del Archivo PDF')

    fecha_factura_str = fields.Char(string='Fecha / Mes Formateado', compute='_compute_fecha_factura_str', store=True, help="Fecha y mes en formato legible en español (ej. 15 de Agosto de 2026).")

    renta_mensual = fields.Monetary(string='Renta Mensual', currency_field='currency_id', default=0.0, tracking=True, help="Monto total acumulado por renta fija de planes corporativos de voz y data.")
    renta_otros_servicios = fields.Monetary(string='Renta Otros Servicios', currency_field='currency_id', default=0.0, tracking=True, help="Servicios adicionales y paquetes complementarios contratados en la cuenta.")
    uso_data_movil = fields.Monetary(string='Uso Data Móvil', currency_field='currency_id', default=0.0, tracking=True, help="Consumo excedente de datos móviles no incluidos en los planes fijos.")
    llamadas_roaming = fields.Monetary(string='Llamadas Roaming', currency_field='currency_id', default=0.0, tracking=True, help="Consumos por llamadas de Larga Distancia Internacional (LDI) o Roaming.")
    otros_cargos_creditos = fields.Monetary(string='Otros Cargos / Créditos (CR)', currency_field='currency_id', default=0.0, tracking=True, help="Cargos extraordinarios, notas de crédito o descuentos corporativos globales a nivel de cuenta.")

    subtotal = fields.Monetary(string='Subtotal Factura', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True, help="Base imponible de la factura antes de aplicar los impuestos de ley (RD$).")
    itbis_monto = fields.Monetary(string='ITBIS (18%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True, help="Impuesto a la Transferencia de Bienes Industrializados y Servicios (18%).")
    cdt_monto = fields.Monetary(string='CDT (2%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True, help="Contribución al Desarrollo de las Telecomunicaciones (2%).")
    isc_monto = fields.Monetary(string='ISC (10%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True, help="Impuesto Selectivo al Consumo de Telecomunicaciones (10%).")
    total_mes = fields.Monetary(string='Total del Mes', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True, help="Gran Total final de la factura Claro en RD$ a pagar (Subtotal + Impuestos).")

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

    total_lineas_sum = fields.Monetary(
        string='Suma Consumo Líneas (RD$)',
        compute='_compute_kpis',
        store=True,
        currency_field='currency_id',
        tracking=True
    )
    diferencia_conciliacion = fields.Monetary(
        string='Ajuste Nivel Cuenta (RD$)',
        compute='_compute_kpis',
        store=True,
        currency_field='currency_id',
        tracking=True
    )
    estado_cuadre = fields.Selection([
        ('cuadrado', 'Cuadrado Exacto'),
        ('ajuste_cuenta', 'Ajuste Corporativo Nivel Cuenta'),
        ('desviacion', 'Desviación Significativa')
    ], string='Estado de Conciliación', compute='_compute_kpis', store=True, tracking=True)

    banner_conciliacion_html = fields.Html(
        string='Resumen de Conciliación Nivel Cuenta vs. Líneas',
        compute='_compute_kpis',
        store=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('flota.factura.conciliacion') or _('FAC-CLARO-%s') % fields.Date.today()
        return super(FlotaFacturaConciliacion, self).create(vals_list)

    @api.depends('fecha_factura')
    def _compute_fecha_factura_str(self):
        meses = {
            1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
            5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
            9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
        }
        for rec in self:
            if rec.fecha_factura:
                m_name = meses.get(rec.fecha_factura.month, '')
                rec.fecha_factura_str = f"{rec.fecha_factura.day} de {m_name} de {rec.fecha_factura.year}"
            else:
                rec.fecha_factura_str = ''

    def action_set_draft(self):
        self.ensure_one()
        self.write({'estado': 'draft'})
        self.message_post(body=_("El estado de la conciliación fue restablecido a <b>Borrador</b>."))

    def action_set_procesando(self):
        self.ensure_one()
        self.write({'estado': 'procesando'})
        self.message_post(body=_("El estado de la conciliación fue cambiado a <b>Procesando</b>."))

    @api.depends('renta_mensual', 'renta_otros_servicios', 'uso_data_movil', 'llamadas_roaming', 'otros_cargos_creditos')
    def _compute_totales_factura(self):
        for rec in self:
            sub = rec.renta_mensual + rec.renta_otros_servicios + rec.uso_data_movil + rec.llamadas_roaming + rec.otros_cargos_creditos
            rec.subtotal = sub
            rec.itbis_monto = sub * 0.18
            rec.cdt_monto = sub * 0.02
            rec.isc_monto = sub * 0.10
            rec.total_mes = sub + rec.itbis_monto + rec.cdt_monto + rec.isc_monto

    @api.depends('linea_ids', 'linea_ids.total_linea', 'linea_ids.estado_linea', 'linea_ids.monto_uso_adicional', 'linea_ids.monto_roaming', 'total_mes')
    def _compute_kpis(self):
        for rec in self:
            rec.count_lineas = len(rec.linea_ids)
            excesos = rec.linea_ids.filtered(lambda l: l.estado_linea in ['exceso_data', 'exceso_roaming'])
            rec.count_excesos = len(excesos)
            rec.monto_excesos = sum(excesos.mapped(lambda l: l.monto_uso_adicional + l.monto_roaming))

            tot_lineas = sum(rec.linea_ids.mapped('total_linea'))
            rec.total_lineas_sum = tot_lineas
            diff = rec.total_mes - tot_lineas
            rec.diferencia_conciliacion = diff

            if abs(diff) < 0.01:
                rec.estado_cuadre = 'cuadrado'
                rec.banner_conciliacion_html = (
                    '<div class="alert alert-success d-flex align-items-center mb-3 shadow-sm" role="alert">'
                    '<i class="fa fa-check-circle fs-4 me-2"></i>'
                    '<div><strong>Conciliación Perfecta:</strong> La suma de consumo de todas las líneas de empleados (RD$%s) coincide exactamente con el Total de la Factura Claro (RD$%s).</div>'
                    '</div>'
                ) % (f"{tot_lineas:,.2f}", f"{rec.total_mes:,.2f}")
            elif abs(diff) < 50000.0:
                rec.estado_cuadre = 'ajuste_cuenta'
                rec.banner_conciliacion_html = (
                    '<div class="alert alert-info d-flex align-items-center mb-3 shadow-sm" role="alert">'
                    '<i class="fa fa-info-circle fs-4 me-2"></i>'
                    '<div>'
                    '<strong>Conciliado con Ajuste Corporativo Nivel Cuenta:</strong><br/>'
                    'Sumatoria Líneas Empleados: <strong>RD$%s</strong> | Total Factura Claro: <strong>RD$%s</strong> | '
                    'Diferencia Nivel Cuenta (Descuento/Crédito Global): <strong>RD$%s</strong>.'
                    '</div>'
                    '</div>'
                ) % (f"{tot_lineas:,.2f}", f"{rec.total_mes:,.2f}", f"{diff:,.2f}")
            else:
                rec.estado_cuadre = 'desviacion'
                rec.banner_conciliacion_html = (
                    '<div class="alert alert-warning d-flex align-items-center mb-3 shadow-sm" role="alert">'
                    '<i class="fa fa-exclamation-triangle fs-4 me-2"></i>'
                    '<div>'
                    '<strong>Desviación Significativa Nivel Cuenta:</strong><br/>'
                    'Existe una diferencia de <strong>RD$%s</strong> entre el total de las líneas (RD$%s) y la factura general (RD$%s).'
                    '</div>'
                    '</div>'
                ) % (f"{diff:,.2f}", f"{tot_lineas:,.2f}", f"{rec.total_mes:,.2f}")

    def action_aplicar_linea_ajuste_corporativo(self):
        """ Aplica la diferencia de Ajuste Corporativo Nivel Cuenta en Rubros Generales de Factura Claro sin alterar la lista de empleados """
        for rec in self:
            # Elimina cualquier línea fantasma CUENTA-GLOBAL previa si existiera
            dummy_lines = rec.linea_ids.filtered(lambda l: l.numero_flota == 'CUENTA-GLOBAL')
            if dummy_lines:
                dummy_lines.unlink()

            diff = rec.diferencia_conciliacion
            if abs(diff) < 0.01:
                raise UserError(_("La factura ya está totalmente cuadrada con las líneas de empleados."))
            
            # Ajustar otros_cargos_creditos (Rubros Generales) descontando la base antes de impuestos (30%: ITBIS 18% + CDT 2% + ISC 10%)
            base_ajuste = diff / 1.30
            rec.otros_cargos_creditos -= base_ajuste
            rec._compute_totales_factura()
            rec._compute_kpis()
            rec.message_post(body=_("Se aplicó el <b>Ajuste Corporativo Nivel Cuenta</b> de RD$%s directamente en Rubros Generales de Factura Claro.") % f"{diff:,.2f}")

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
                    if emp.estado != 'active' or not emp.en_ultima_factura:
                        emp.write({'estado': 'active', 'en_ultima_factura': True})
                        emp.message_post(body=_("Estado del empleado actualizado a <b>Activo</b> al ser detectado en la conciliación de Claro (%s).") % rec.periodo)
                else:
                    if emp.estado != 'inactive' or emp.en_ultima_factura:
                        emp.write({'estado': 'inactive', 'en_ultima_factura': False})
                        emp.message_post(body=_("<b>Revisión de Flota:</b> Empleado NO detectado en la factura Claro del periodo (%s). Marcado como Faltante / Inactivo.") % rec.periodo)

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
        # 1. Intentar primero con pypdf/PyPDF2 (Rápido, ultra liviano en RAM)
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
        except Exception as e:
            _logger.warning("Error extrayendo con PyPDF/PyPDF2: %s", str(e))

        if text and len(text.strip()) >= 100:
            return text

        # 2. Fallback a pdfplumber si pypdf no extrajo texto completo
        try:
            import io
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    text += (page.extract_text() or "") + "\n"
        except Exception as e2:
            _logger.warning("Error extrayendo con pdfplumber: %s", str(e2))
                
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

        # Extracción de Fecha de Factura desde el PDF si está presente (Ej. Fecha de Emisión: 13/08/2026)
        import datetime
        m_fecha = re.search(r'Fecha\s*(?:de\s*factura|facturaci[oó]n|emisi[oó]n)?:?\s*([0-9]{1,2})[/-]([0-9]{1,2})[/-]([0-9]{2,4})', pdf_text, re.IGNORECASE)
        if m_fecha:
            d, m, y = int(m_fecha.group(1)), int(m_fecha.group(2)), int(m_fecha.group(3))
            if y < 100:
                y += 2000
            try:
                self.fecha_factura = datetime.date(y, m, d)
            except Exception:
                pass

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

        m_cred = re.search(r'Otros\s+cargos,?\s+cr[eé]ditos[^\n]*?([0-9,]+\.[0-9]{2}\s*(?:CR)?)', pdf_text, re.IGNORECASE)
        if m_cred:
            t_c = m_cred.group(1).upper()
            val = float(re.sub(r'[^0-9.]', '', t_c.replace(',', '')) or 0)
            cred_m = -val if ('CR' in t_c or '-' in t_c) else val

        # Ajuste automático del Total de Factura si viene especificado en la carátula de Claro
        m_tot_pdf = re.search(r'(?:Total\s+del\s+Mes|Total\s+a\s+Pagar|Total\s+Factura)\s*[\$RD\s]*([0-9,]+\.[0-9]{2})', pdf_text, re.IGNORECASE)
        if m_tot_pdf:
            pdf_total_mes_val = float(m_tot_pdf.group(1).replace(',', ''))
            if pdf_total_mes_val > 0:
                subtotal_prev = renta_m + renta_o + data_m + roam_m + cred_m
                total_prev = subtotal_prev * 1.30
                diff = pdf_total_mes_val - total_prev
                if abs(diff) > 0.001 and abs(diff) < 10000.0:
                    cred_m += (diff / 1.30)

        emp_map = _build_empleado_phone_map(self.env)
        lineas_vals = []
        lines = pdf_text.split('\n')
        seen_phones = set()

        for line_raw in lines:
            line_str = _fix_claro_pdf_line(line_raw)
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

            line_no_phone = line_str[:m_phone.start()] + ' ' + line_str[m_phone.end():]
            tokens = line_no_phone.split()
            num_values = []
            for tok in tokens:
                m_val = re.match(r'^(-?[0-9,]+\.[0-9]{2}(?:CR)?)$', tok, re.IGNORECASE)
                if m_val:
                    t_str = m_val.group(1).upper()
                    is_cr = 'CR' in t_str or t_str.startswith('-')
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
            imp_pdf = 0.0

            # Estructura exacta de la tabla de 7 columnas numéricas de Factura Claro Dominicana:
            # Col 1: Otros Servicios y Data Móvil (Servicios fijos / Paquetes adicionales)
            # Col 2: Uso local y Data Móvil (Exceso Data / Voz local)
            # Col 3: Renta Plan / Llamadas larga distancia / Roaming
            # Col 4: Financiamiento equipos
            # Col 5: Otros cargos, créditos o descuentos (positivo o negativo con CR/-)
            # Col 6: Impuestos
            # Col 7: Total (RD$)
            if len(num_values) == 7:
                r_otros = num_values[0]
                uso_add = num_values[1]
                r_plan = num_values[2]
                finan = num_values[3]
                cred = num_values[4]
                imp_pdf = num_values[5]
            elif len(num_values) == 6:
                r_otros = num_values[0]
                uso_add = num_values[1]
                r_plan = num_values[2]
                finan = num_values[3]
                cred = num_values[4]
            elif len(num_values) == 5:
                r_otros = num_values[0]
                uso_add = num_values[1]
                r_plan = num_values[2]
                cred = num_values[3]
            elif len(num_values) == 4:
                r_otros = num_values[0]
                uso_add = num_values[1]
                cred = num_values[2]
            elif len(num_values) == 3:
                r_otros = num_values[0]
                cred = num_values[1]
            elif len(num_values) == 2:
                r_plan = num_values[0]
            elif len(num_values) == 1:
                r_plan = num_values[0]

            emp = emp_map.get(clean_phone) or emp_map.get(clean_phone[-10:]) or (emp_map.get(clean_phone[-7:]) if len(clean_phone) >= 7 else None)
            if not emp:
                default_dept = self.env['flota.departamento'].search([], limit=1)
                default_ubic = self.env['flota.ubicacion'].search([], limit=1)
                emp_name = f"Empleado Flota {clean_phone}"
                emp = self.env['flota.empleado'].create({
                    'name': emp_name,
                    'numero_flota': clean_phone,
                    'cargo': 'Asignación Automática Claro',
                    'departamento_id': default_dept.id if default_dept else False,
                    'ubicacion_id': default_ubic.id if default_ubic else False,
                    'estado': 'active',
                    'en_ultima_factura': True,
                    'es_nuevo_auto': True,
                    'notas': f'Nuevo número registrado desde Factura Claro ({self.periodo}). Complete la ficha de empleado.'
                })
                emp.message_post(body=_("Empleado registrado automáticamente al aparecer un nuevo número en la factura de Claro (%s): <b>%s</b>.") % (self.periodo, clean_phone))
                emp_map[clean_phone] = emp
                if len(clean_phone) >= 10:
                    emp_map[clean_phone[-10:]] = emp
                if len(clean_phone) >= 7:
                    emp_map[clean_phone[-7:]] = emp

            lineas_vals.append({
                'conciliacion_id': self.id,
                'numero_flota': clean_phone,
                'empleado_id': emp.id,
                'monto_renta_plan': r_plan,
                'monto_otros_servicios': r_otros,
                'monto_uso_adicional': uso_add,
                'monto_roaming': roam,
                'monto_financiamiento': finan,
                'monto_creditos': cred,
                'monto_impuestos_pdf': imp_pdf,
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
    fecha_factura = fields.Date(string='Fecha de Factura', related='conciliacion_id.fecha_factura', store=True, readonly=True)
    fecha_subida = fields.Datetime(string='Fecha de Subida', related='conciliacion_id.fecha_subida', store=True, readonly=True)
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
    monto_impuestos_pdf = fields.Monetary(string='Impuestos PDF', currency_field='currency_id', default=0.0)

    subtotal_linea = fields.Monetary(string='Subtotal Línea', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    itbis_linea = fields.Monetary(string='ITBIS (18%)', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    cdt_linea = fields.Monetary(string='CDT (2%)', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    isc_linea = fields.Monetary(string='ISC (10%)', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    total_linea = fields.Monetary(string='Total Línea (RD$)', compute='_compute_linea_totals', store=True, currency_field='currency_id')

    currency_id = fields.Many2one('res.currency', string='Moneda', related='conciliacion_id.currency_id', store=True)

    estado_linea = fields.Selection([
        ('ok', 'Normal'),
        ('sin_consumo', 'Sin Consumo / RD$0'),
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

    @api.depends('monto_renta_plan', 'monto_otros_servicios', 'monto_uso_adicional', 'monto_roaming', 'monto_financiamiento', 'monto_creditos', 'monto_impuestos_pdf')
    def _compute_linea_totals(self):
        for rec in self:
            sub = rec.monto_renta_plan + rec.monto_otros_servicios + rec.monto_uso_adicional + rec.monto_roaming + rec.monto_financiamiento + rec.monto_creditos
            rec.subtotal_linea = sub
            
            imp = rec.monto_impuestos_pdf if rec.monto_impuestos_pdf > 0 else (sub * 0.30)
            rec.itbis_linea = imp * 0.60
            rec.cdt_linea = imp * (1.0 / 15.0)
            rec.isc_linea = imp * (1.0 / 3.0)
            rec.total_linea = sub + imp

    @api.depends('empleado_id', 'total_linea', 'monto_uso_adicional', 'monto_roaming')
    def _compute_estado_linea(self):
        for rec in self:
            if not rec.empleado_id:
                rec.estado_linea = 'desconocido'
            elif rec.total_linea == 0:
                rec.estado_linea = 'sin_consumo'
            elif rec.monto_roaming > 0.01:
                rec.estado_linea = 'exceso_roaming'
            elif rec.monto_uso_adicional > 0.01:
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
