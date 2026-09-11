import re


CLARO_COLUMN_NAMES = [
    'Otros servicios y Data Móvil',
    'Uso local y Data Móvil',
    'Llamadas larga distancia, roaming y otras llamadas',
    'Financiamiento equipos',
    'Otros cargos, créditos o descuentos',
    'Impuestos',
    'Total (RD$)',
]

PHONE_RE = re.compile(r'(?:1[\s-]?)?(?:\()?((?:8[0249]\d))(?:\))?[\s-]?(\d{3})[\s-]?(\d{4})')


def normalize_phone(phone_str):
    if not phone_str:
        return ''
    digits = re.sub(r'\D', '', str(phone_str))
    if len(digits) > 10 and digits.startswith('1'):
        digits = digits[-10:]
    return digits


def build_empleado_phone_map(env):
    emp_map = {}
    emps = env['flota.empleado'].with_context(active_test=False).search([])
    for emp in emps:
        if not emp.numero_flota:
            continue
        norm = normalize_phone(emp.numero_flota)
        if not norm:
            continue
        emp_map[norm] = emp
        if len(norm) >= 10:
            emp_map[norm[-10:]] = emp
        if len(norm) >= 7:
            emp_map[norm[-7:]] = emp
    return emp_map


def fix_claro_pdf_line(line_str):
    if not line_str:
        return ''
    fixed = re.sub(r'(\.\d{2}(?:CR)?)(8[0249]\d)', r'\1 \2', line_str, flags=re.IGNORECASE)
    fixed = re.sub(r'(\.\d{2}(?:CR)?)(?=[-\d])', r'\1 ', fixed, flags=re.IGNORECASE)
    return fixed


def parse_money_token(token):
    if not token:
        return 0.0
    match = re.match(r'^(-?[0-9,]+\.[0-9]{2}(?:CR)?)$', token, re.IGNORECASE)
    if not match:
        return 0.0
    value_str = match.group(1).upper()
    is_credit = 'CR' in value_str or value_str.startswith('-')
    value = float(re.sub(r'[^0-9.]', '', value_str.replace(',', '')) or 0)
    if is_credit:
        value = -abs(value)
    return value


def extract_claro_money_values(text):
    if not text:
        return []
    raw_tokens = re.findall(r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?(?:CR)?', str(text), flags=re.IGNORECASE)
    values = []
    for token in raw_tokens:
        value = parse_money_token(token)
        # Preserve zero-valued PDF cells so later columns keep their positions.
        values.append(value)
    return values


def extract_claro_phone_row(line_text):
    if not line_text:
        return None
    line = fix_claro_pdf_line(line_text)
    m_phone = PHONE_RE.search(line)
    if not m_phone:
        return None
    phone = normalize_phone(m_phone.group(0))
    if not (phone.startswith(('809', '829', '849')) and len(phone) == 10):
        return None

    row_values = extract_claro_money_values(line[m_phone.end():])
    if len(row_values) < 4:
        row_values = extract_claro_money_values(line)

    if len(row_values) < 4:
        return None

    return {
        'phone': phone,
        'values': row_values,
    }


def normalize_claro_numeric_values(num_values, source_extractor='pdfplumber'):
    # El PDF de Claro imprime el encabezado "Otros Servicios y Data Móvil | Uso local
    # y Data Móvil | Llamadas larga distancia, roaming y otras llamadas | Financiamiento
    # equipos | Otros cargos, créditos o descuentos | Impuestos | Total(RD$)" y ese es
    # el orden visual REAL de las columnas (confirmado con pdfplumber y con la imagen
    # de la factura). Cuando el texto se extrae con pdfplumber, los valores numéricos
    # de cada línea vienen exactamente en ese mismo orden y no se debe alterar nada.
    #
    # Sin embargo, cuando el texto se extrae con pypdf/PyPDF2 (el extractor que se usa
    # primero en producción por ser más liviano), la librería reordena internamente los
    # tokens de esta tabla específica. Se confirmó estadísticamente (768 líneas de 3
    # facturas reales distintas, 100% de coincidencia) que, respecto al orden visual real
    # [OtrosServ, UsoLocal, Llamadas, Financ, OtrosCargos, Impuestos, Total], pypdf entrega:
    #   visual[0] (Otros Servicios)        = pypdf[2]
    #   visual[1] (Uso local)              = pypdf[0]
    #   visual[2] (Llamadas larga dist.)   = pypdf[3]
    #   visual[3] (Financiamiento equipos) = pypdf[1]
    #   visual[4:] (resto de columnas)     = pypdf[4:] (sin cambios)
    values = list(num_values)
    if source_extractor == 'pypdf' and len(values) >= 4:
        reordered = [values[2], values[0], values[3], values[1]] + values[4:]
        return reordered
    return values


def map_claro_columns(num_values, source_extractor='pdfplumber'):
    values = normalize_claro_numeric_values(list(num_values), source_extractor=source_extractor)
    line = {
        'otros_servicios_datos': 0.0,
        'uso_local_data_movil': 0.0,
        'llamadas_roaming_otras_llamadas': 0.0,
        'monto_roaming': 0.0,
        'financiamiento_equipos': 0.0,
        'otros_cargos_descuentos': 0.0,
        'impuestos': 0.0,
        'total': 0.0,
    }

    if len(values) >= 1:
        line['otros_servicios_datos'] = values[0]
    if len(values) >= 2:
        line['uso_local_data_movil'] = values[1]
    if len(values) >= 3:
        line['llamadas_roaming_otras_llamadas'] = values[2]
    if len(values) >= 4:
        line['financiamiento_equipos'] = values[3]
    if len(values) >= 5:
        line['otros_cargos_descuentos'] = values[4]
    if len(values) >= 6:
        line['impuestos'] = values[5]
    if len(values) >= 7:
        line['total'] = values[6]
    return line
