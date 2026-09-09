import json
import logging
import base64
import io
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from .flota_factura_claro_parser import (
    CLARO_COLUMN_NAMES,
    build_empleado_phone_map,
    extract_claro_phone_row,
    fix_claro_pdf_line,
    map_claro_columns,
    normalize_phone,
    parse_money_token,
)

_logger = logging.getLogger(__name__)


def _normalize_phone(phone_str):
    return normalize_phone(phone_str)


def _build_empleado_phone_map(env):
    return build_empleado_phone_map(env)


def _fix_claro_pdf_line(line_str):
    return fix_claro_pdf_line(line_str)


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
    otros_cargos_creditos = fields.Monetary(string='Otros cargos, créditos o descuentos', currency_field='currency_id', default=0.0, tracking=True, help="Cargos extraordinarios, notas de crédito o descuentos corporativos globales a nivel de cuenta.")

    subtotal = fields.Monetary(string='Subtotal Factura', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True, help="Base imponible de la factura antes de aplicar los impuestos de ley (RD$).")
    subtotal_factura = fields.Monetary(string='Subtotal Factura', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True, help="Base imponible de la factura antes de aplicar los impuestos de ley (RD$).")
    base_gravable_itbis = fields.Monetary(string='Base Gravable ITBIS', compute='_compute_totales_factura', store=True, currency_field='currency_id', help="Monto total gravado con el 18% de ITBIS.")
    base_gravable_cdt = fields.Monetary(string='Base Gravable CDT', compute='_compute_totales_factura', store=True, currency_field='currency_id', help="Monto total gravado con el 2% de CDT (Subtotal menos Conceptos Excluidos).")
    base_gravable_isc = fields.Monetary(string='Base Gravable ISC', compute='_compute_totales_factura', store=True, currency_field='currency_id', help="Monto total gravado con el 10% de ISC.")
    ajustes_excluidos_cdt = fields.Monetary(string='Conceptos Excluidos CDT', compute='_compute_totales_factura', store=True, readonly=False, currency_field='currency_id', help="Conceptos/Ajustes que NO gravan CDT (ej. Cargo por Pago Atrasado / Mora).")

    itbis_monto = fields.Monetary(string='ITBIS (18%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True, help="Impuesto a la Transferencia de Bienes Industrializados y Servicios (18%).")
    cdt_monto = fields.Monetary(string='CDT informado (2%)', currency_field='currency_id', default=0.0, tracking=True, help="Monto CDT usado para obtener la base gravable mediante CDT / 2%.")
    isc_monto = fields.Monetary(string='ISC (10%)', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True, help="Impuesto Selectivo al Consumo de Telecomunicaciones (10%).")
    total_mes = fields.Monetary(string='Total del Mes', compute='_compute_totales_factura', store=True, currency_field='currency_id', tracking=True, help="Gran Total final de la factura Claro en RD$ a pagar (Subtotal + Impuestos).")
    total_factura_pdf = fields.Monetary(string='Total Factura Claro (PDF)', currency_field='currency_id', default=0.0, tracking=True, help="Monto 'Total del Mes' impreso literalmente en la carátula del PDF de Claro. Se usa como referencia oficial para validar la conciliación.")

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
    concepto_ids = fields.One2many('flota.factura.concepto', 'conciliacion_id', string='Conceptos y Ajustes de Factura')

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
    estado_cuadre = fields.Selection([
        ('cuadrado', 'Cuadrado Exacto'),
        ('desviacion', 'Con Diferencia')
    ], string='Estado de Conciliación', compute='_compute_kpis', store=True, tracking=True)

    banner_conciliacion_html = fields.Html(
        string='Resumen de Conciliación Factura vs. Líneas',
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

    @api.depends(
        'renta_mensual', 'renta_otros_servicios', 'uso_data_movil', 'llamadas_roaming',
        'otros_cargos_creditos', 'cdt_monto'
    )
    def _compute_totales_factura(self):
        for rec in self:
            # Los créditos y descuentos se almacenan negativos y se suman al subtotal.
            sub = (
                rec.renta_mensual
                + rec.renta_otros_servicios
                + rec.uso_data_movil
                + rec.llamadas_roaming
                + rec.otros_cargos_creditos
            )
            rec.subtotal = sub
            rec.subtotal_factura = sub
            rec.base_gravable_itbis = sub
            rec.base_gravable_isc = sub
            rec.base_gravable_cdt = rec.cdt_monto / 0.02 if rec.cdt_monto else 0.0
            rec.ajustes_excluidos_cdt = sub - rec.base_gravable_cdt
            rec.itbis_monto = sub * 0.18
            rec.isc_monto = sub * 0.10
            rec.total_mes = sub + rec.itbis_monto + rec.isc_monto + rec.cdt_monto

    @api.depends('linea_ids', 'linea_ids.total', 'linea_ids.total_linea', 'linea_ids.estado_linea', 'linea_ids.uso_local_data_movil', 'linea_ids.monto_roaming', 'total_mes', 'total_factura_pdf')
    def _compute_kpis(self):
        for rec in self:
            rec.count_lineas = len(rec.linea_ids)
            excesos = rec.linea_ids.filtered(lambda l: l.estado_linea in ['exceso_data', 'exceso_roaming'])
            rec.count_excesos = len(excesos)
            rec.monto_excesos = sum(excesos.mapped(lambda l: l.uso_local_data_movil + l.monto_roaming))

            tot_lineas = sum(rec.linea_ids.mapped('total'))
            rec.total_lineas_sum = tot_lineas
            # La conciliación se valida contra el Total de la Factura Claro impreso en el PDF, no contra la suma de líneas de empleados.
            diff = rec.total_factura_pdf - rec.total_mes

            if abs(diff) < 0.01:
                rec.estado_cuadre = 'cuadrado'
                rec.banner_conciliacion_html = False
            else:
                rec.estado_cuadre = 'desviacion'
                rec.banner_conciliacion_html = (
                    '<div class="alert alert-warning d-flex align-items-center mb-3 shadow-sm" role="alert">'
                    '<i class="fa fa-exclamation-triangle fs-4 me-2"></i>'
                    '<div>'
                    '<strong>Diferencia Detectada en Conciliación:</strong><br/>'
                    'El Total de la Factura Claro impreso en el PDF es de <strong>RD$%s</strong>.<br/>'
                    'El Total del Mes calculado por el sistema es de <strong>RD$%s</strong>, sumando el Subtotal (<strong>RD$%s</strong>) más los impuestos '
                    '(ITBIS 18%%: <strong>RD$%s</strong>, ISC 10%%: <strong>RD$%s</strong> y CDT 2%%: <strong>RD$%s</strong>).<br/>'
                    'Existe una diferencia de <strong>RD$%s</strong> entre el monto de la factura y el monto calculado por el sistema. '
                    'Revise los valores de Renta, Otros cargos/créditos y CDT capturados de la factura.'
                    '</div>'
                    '</div>'
                ) % (
                    f"{rec.total_factura_pdf:,.2f}",
                    f"{rec.total_mes:,.2f}",
                    f"{rec.subtotal:,.2f}",
                    f"{rec.itbis_monto:,.2f}",
                    f"{rec.isc_monto:,.2f}",
                    f"{rec.cdt_monto:,.2f}",
                    f"{abs(diff):,.2f}"
                )


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

            if seen_emp_ids:
                self.env['flota.empleado'].browse(list(seen_emp_ids))._update_facturacion_stats()

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
            tot_gral = rec.total_mes
            for d_id, data in dept_totals.items():
                pct = (data['monto_total'] / tot_gral) if tot_gral else 0.0
                resumen_vals.append((0, 0, {
                    'conciliacion_id': rec.id,
                    'departamento_id': data['departamento_id'],
                    'ubicacion_id': data['ubicacion_id'],
                    'cantidad_empleados': data['cantidad_empleados'],
                    'monto_subtotal': data['monto_subtotal'],
                    'monto_total': data['monto_total'],
                    'porcentaje_gasto': pct,
                    'currency_id': rec.currency_id.id
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
        cdt_m = 0.0

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

        # El monto puede aparecer antes o después de la etiqueta "CDT - 2%" según el layout del PDF de Claro
        m_cdt = re.search(r'CDT\s*(?:-|:)\s*2%[^0-9]*([0-9,]+\.[0-9]{2})', pdf_text, re.IGNORECASE)
        if not m_cdt:
            m_cdt = re.search(r'([0-9,]+\.[0-9]{2})\s*CDT\s*(?:-|:)\s*2%', pdf_text, re.IGNORECASE)
        if m_cdt:
            cdt_m = float(m_cdt.group(1).replace(',', ''))

        # Total de Factura Claro impreso literalmente en el PDF (fuente oficial para validar la conciliación)
        total_pdf_m = 0.0
        m_tot_pdf = re.search(r'Total\s+del\s+Mes\s*[\$RD\s]*([0-9,]+\.[0-9]{2})', pdf_text, re.IGNORECASE)
        if not m_tot_pdf:
            m_tot_pdf = re.search(r'(?:Total\s+a\s+Pagar|Total\s+Factura)\s*[\$RD\s]*([0-9,]+\.[0-9]{2})', pdf_text, re.IGNORECASE)
        if m_tot_pdf:
            total_pdf_m = float(m_tot_pdf.group(1).replace(',', ''))

        emp_map = _build_empleado_phone_map(self.env)
        lineas_vals = []
        seen_phones = set()

        for line_raw in pdf_text.split('\n'):
            row = extract_claro_phone_row(line_raw)
            if not row:
                continue

            clean_phone = row['phone']
            if clean_phone in ('8092201212', '8092201111'):
                continue
            if clean_phone in seen_phones:
                continue
            seen_phones.add(clean_phone)

            values = row['values']
            if len(values) < 4:
                continue

            ordered_values = values[:7]

            mapped_values = map_claro_columns(ordered_values)
            emp = emp_map.get(clean_phone) or emp_map.get(clean_phone[-10:]) or (emp_map.get(clean_phone[-7:]) if len(clean_phone) >= 7 else None)
            if not emp:
                emp_name = f"Empleado Flota {clean_phone}"
                emp = self.env['flota.empleado'].create({
                    'name': emp_name,
                    'numero_flota': clean_phone,
                    'cargo': 'Asignación Automática Claro',
                    'departamento_id': False,
                    'ubicacion_id': False,
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
                'llamadas_roaming_otras_llamadas': mapped_values.get('llamadas_roaming_otras_llamadas', 0.0),
                'otros_servicios_datos': mapped_values.get('otros_servicios_datos', 0.0),
                'uso_local_data_movil': mapped_values.get('uso_local_data_movil', 0.0),
                'monto_roaming': mapped_values.get('monto_roaming', 0.0),
                'financiamiento_equipos': mapped_values.get('financiamiento_equipos', 0.0),
                'otros_cargos_descuentos': mapped_values.get('otros_cargos_descuentos', 0.0),
                'impuestos': mapped_values.get('impuestos', 0.0),
                'total': mapped_values.get('total', 0.0),
            })

        self.write({
            'renta_mensual': renta_m,
            'renta_otros_servicios': renta_o,
            'uso_data_movil': data_m,
            'llamadas_roaming': roam_m,
            'otros_cargos_creditos': cred_m,
            'cdt_monto': cdt_m,
            'total_factura_pdf': total_pdf_m,
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
        """Exporta la factura y el consolidado departamental a un libro Excel."""
        self.ensure_one()
        diff = self.total_mes - self.total_lineas_sum
        if abs(diff) >= 0.01:
            raise UserError(_(
                "No se puede exportar la factura a Excel porque existe una diferencia de RD$%s entre el Total de la Factura (RD$%s) y la Suma de Líneas por Empleado (RD$%s).\n\n"
                "Por favor, revise las líneas para que ambos montos coincidan antes de exportar el documento."
            ) % (f"{diff:,.2f}", f"{self.total_mes:,.2f}", f"{self.total_lineas_sum:,.2f}"))

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

        ws_dept = wb.create_sheet("Consolidado por Departamento")
        dept_headers = [
            "DEPARTAMENTO",
            "CEDI / UBICACIÓN",
            "EMPLEADOS",
            "SUBTOTAL (RD$)",
            "TOTAL DEPTO (RD$)",
            "% DEL TOTAL GENERAL",
        ]
        for col_num, header in enumerate(dept_headers, 1):
            cell = ws_dept.cell(row=1, column=col_num, value=header)
            cell.fill = header_fill
            cell.font = header_font

        for row_num, summary in enumerate(self.resumen_depto_ids, 2):
            ws_dept.cell(row=row_num, column=1, value=summary.departamento_id.name or "Sin departamento")
            ws_dept.cell(row=row_num, column=2, value=summary.ubicacion_id.name or "Sin ubicación")
            ws_dept.cell(row=row_num, column=3, value=summary.cantidad_empleados)
            subtotal_cell = ws_dept.cell(row=row_num, column=4, value=summary.monto_subtotal)
            total_cell = ws_dept.cell(row=row_num, column=5, value=summary.monto_total)
            subtotal_cell.number_format = '"RD$"#,##0.00'
            total_cell.number_format = '"RD$"#,##0.00'
            pct_cell = ws_dept.cell(row=row_num, column=6, value=summary.porcentaje_gasto)
            pct_cell.number_format = '0.00%'

        for column_cells in ws_dept.columns:
            max_len = max(len(str(cell.value or '')) for cell in column_cells)
            column_letter = openpyxl.utils.get_column_letter(column_cells[0].column)
            ws_dept.column_dimensions[column_letter].width = max(max_len + 3, 16)

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
            ("SUBTOTAL FACTURA", self.subtotal_factura),
            ("(-) Conceptos Excluidos CDT", self.ajustes_excluidos_cdt),
            ("(=) Base Gravable CDT", self.base_gravable_cdt),
            ("ITBIS - 18%", self.itbis_monto),
            ("CDT - 2%", self.cdt_monto),
            ("ISC - 10%", self.isc_monto),
            ("TOTAL DEL MES", self.total_mes),
        ]

        for name, val in rubros:
            c_name = ws.cell(row=current_row, column=1, value=name)
            c_val = ws.cell(row=current_row, column=2, value=val)
            c_val.number_format = '"RD$"#,##0.00'
            
            if name in ["SUBTOTAL FACTURA", "(=) Base Gravable CDT", "TOTAL DEL MES"]:
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

        month_names = (
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
        )
        month_name = month_names[self.fecha_factura.month - 1] if self.fecha_factura else (self.periodo or "Sin fecha")
        attachment = self.env['ir.attachment'].create({
            'name': f'Factura Claro {month_name}.xlsx',
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

    llamadas_roaming_otras_llamadas = fields.Monetary(string='Llamadas, roaming y otras llamadas', currency_field='currency_id', default=0.0)
    otros_servicios_datos = fields.Monetary(string='Otros servicios y datos', currency_field='currency_id', default=0.0)
    uso_local_data_movil = fields.Monetary(string='Uso local y data móvil', currency_field='currency_id', default=0.0)
    monto_roaming = fields.Monetary(string='Roaming / LD', currency_field='currency_id', default=0.0)
    financiamiento_equipos = fields.Monetary(string='Financiamiento de equipos', currency_field='currency_id', default=0.0)
    otros_cargos_descuentos = fields.Monetary(string='Otros cargos y descuentos', currency_field='currency_id', default=0.0)
    impuestos = fields.Monetary(string='Impuestos', currency_field='currency_id', default=0.0)
    total = fields.Monetary(
        string='Total',
        currency_field='currency_id',
        default=0.0,
        help='Total de la línea tal como aparece en la factura PDF de Claro.'
    )
    diferencia_pdf = fields.Monetary(
        string='Diferencia PDF',
        compute='_compute_linea_totals',
        store=True,
        currency_field='currency_id',
        help='Diferencia entre el total calculado por Odoo y el total impreso en el PDF.'
    )

    subtotal_linea = fields.Monetary(string='Subtotal Línea', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    itbis_linea = fields.Monetary(string='ITBIS (18%)', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    cdt_linea = fields.Monetary(string='CDT (2%)', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    isc_linea = fields.Monetary(string='ISC (10%)', compute='_compute_linea_totals', store=True, currency_field='currency_id')
    total_linea = fields.Monetary(string='Total Línea (RD$)', compute='_compute_linea_totals', store=True, currency_field='currency_id')

    currency_id = fields.Many2one('res.currency', string='Moneda', related='conciliacion_id.currency_id', store=True)

    estado_linea = fields.Selection([
        ('ok', 'Normal'),
        ('sin_consumo', 'Sin Consumo / RD$0'),
        ('exceso_data_roaming', 'Exceso Data y Roaming'),
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

    @api.depends('llamadas_roaming_otras_llamadas', 'otros_servicios_datos', 'uso_local_data_movil', 'monto_roaming', 'financiamiento_equipos', 'otros_cargos_descuentos', 'impuestos', 'total')
    def _compute_linea_totals(self):
        for rec in self:
            sub = rec.llamadas_roaming_otras_llamadas + rec.otros_servicios_datos + rec.uso_local_data_movil + rec.monto_roaming + rec.financiamiento_equipos + rec.otros_cargos_descuentos
            rec.subtotal_linea = sub
            
            base_imponible = (
                rec.llamadas_roaming_otras_llamadas
                + rec.otros_servicios_datos
                + rec.uso_local_data_movil
                + rec.monto_roaming
                + rec.otros_cargos_descuentos
            )
            imp = rec.impuestos if rec.impuestos > 0 else (base_imponible * 0.30)
            rec.itbis_linea = imp * 0.60
            rec.cdt_linea = imp * (1.0 / 15.0)
            rec.isc_linea = imp * (1.0 / 3.0)
            rec.total_linea = sub + imp
            rec.diferencia_pdf = rec.total_linea - rec.total if rec.total else 0.0

    @api.depends('empleado_id', 'total_linea', 'uso_local_data_movil', 'monto_roaming')
    def _compute_estado_linea(self):
        for rec in self:
            if not rec.empleado_id:
                rec.estado_linea = 'desconocido'
            elif all(abs(value) < 0.01 for value in (
                rec.llamadas_roaming_otras_llamadas,
                rec.otros_servicios_datos,
                rec.uso_local_data_movil,
                rec.monto_roaming,
                rec.financiamiento_equipos,
                rec.otros_cargos_descuentos,
                rec.impuestos,
            )):
                rec.estado_linea = 'sin_consumo'
            elif rec.monto_roaming > 0.01 and rec.uso_local_data_movil > 0.01:
                rec.estado_linea = 'exceso_data_roaming'
            elif rec.monto_roaming > 0.01:
                rec.estado_linea = 'exceso_roaming'
            elif rec.uso_local_data_movil > 0.01:
                rec.estado_linea = 'exceso_data'
            else:
                rec.estado_linea = 'ok'


class FlotaFacturaDepartamentoResumen(models.Model):
    _name = 'flota.factura.departamento.resumen'
    _description = 'Resumen Consolidado de Factura por Departamento'
    _order = 'monto_total desc'

    def _auto_init(self):
        self.env.cr.execute("""
            ALTER TABLE flota_factura_departamento_resumen 
            ADD COLUMN IF NOT EXISTS currency_id INTEGER;
        """)
        return super()._auto_init()

    conciliacion_id = fields.Many2one('flota.factura.conciliacion', string='Factura Conciliación', ondelete='cascade', index=True)
    departamento_id = fields.Many2one('flota.departamento', string='Departamento')
    ubicacion_id = fields.Many2one('flota.ubicacion', string='CEDI / Ubicación')
    cantidad_empleados = fields.Integer(string='Empleados')
    monto_subtotal = fields.Monetary(string='Subtotal Depto', currency_field='currency_id')
    monto_total = fields.Monetary(string='Total Depto (RD$)', currency_field='currency_id')
    porcentaje_gasto = fields.Float(string='% del Total General', digits=(5, 2))
    currency_id = fields.Many2one('res.currency', string='Moneda', related='conciliacion_id.currency_id', store=True, readonly=True)


class FlotaFacturaConcepto(models.Model):
    _name = 'flota.factura.concepto'
    _description = 'Concepto o Ajuste de Factura (Grava / Excluido de CDT)'
    _order = 'id asc'

    conciliacion_id = fields.Many2one('flota.factura.conciliacion', string='Factura Conciliación', ondelete='cascade', index=True)
    nombre_concepto = fields.Char(string='Concepto / Detalle', required=True)
    monto = fields.Monetary(string='Monto (RD$)', currency_field='currency_id', default=0.0)
    currency_id = fields.Many2one('res.currency', related='conciliacion_id.currency_id', store=True, readonly=True)
    grava_itbis = fields.Boolean(string='Grava ITBIS (18%)', default=True)
    grava_cdt = fields.Boolean(string='Grava CDT (2%)', default=True)
    grava_isc = fields.Boolean(string='Grava ISC (10%)', default=True)
    notas = fields.Char(string='Observaciones')

    @api.onchange('nombre_concepto')
    def _onchange_nombre_concepto(self):
        if self.nombre_concepto:
            nombre = self.nombre_concepto.lower()
            keywords_excluidos_cdt = ['pago atrasado', 'mora', 'recargo', 'multa', 'interes', 'atraso', 'cargo por pago']
            if any(kw in nombre for kw in keywords_excluidos_cdt):
                self.grava_cdt = False
                self.notas = _("Excluido automáticamente de CDT (Concepto no gravado con 2% CDT)")

