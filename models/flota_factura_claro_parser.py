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


def normalize_claro_numeric_values(num_values):
    values = list(num_values)
    if len(values) < 7:
        return values

    v0, v1, v2, v3, v4, v5, v6 = values[:7]

    # Evitamos reordenar por defecto. El PDF real de Claro tiene este orden:
    # [Otros servicios, Uso local, Llamadas/roaming, Financiamiento, Otros cargos, Impuestos, Total]
    # Solo debemos hacer swap cuando la variante del PDF está claramente invertida,
    # es decir, la columna de uso local queda a la izquierda con un valor real y la
    # columna de otros servicios queda a la derecha en cero.
    if (
        abs(v0) < 0.01 and abs(v1) > 0.01 and
        abs(v2) < 0.01 and abs(v3) < 0.01 and
        abs(v4) > 0.01
    ):
        return [v1, v0] + values[2:]

    # Si el PDF viene con el orden correcto, no alteramos el orden original.
    return values


def map_claro_columns(num_values):
    values = normalize_claro_numeric_values(list(num_values))
    line = {
        'monto_otros_servicios': 0.0,
        'monto_uso_adicional': 0.0,
        'monto_renta_plan': 0.0,
        'monto_roaming': 0.0,
        'monto_financiamiento': 0.0,
        'monto_creditos': 0.0,
        'monto_impuestos_pdf': 0.0,
        'total_pdf': 0.0,
    }

    if len(values) == 7:
        line['monto_otros_servicios'] = values[0]
        line['monto_uso_adicional'] = values[1]
        line['monto_renta_plan'] = values[2]
        line['monto_financiamiento'] = values[3]
        line['monto_creditos'] = values[4]
        line['monto_impuestos_pdf'] = values[5]
        line['total_pdf'] = values[6]
    elif len(values) == 6:
        line['monto_otros_servicios'] = values[0]
        line['monto_uso_adicional'] = values[1]
        line['monto_renta_plan'] = values[2]
        line['monto_financiamiento'] = values[3]
        line['monto_creditos'] = values[4]
        line['total_pdf'] = values[5]
    elif len(values) == 5:
        line['monto_otros_servicios'] = values[0]
        line['monto_uso_adicional'] = values[1]
        line['monto_renta_plan'] = values[2]
        line['monto_creditos'] = values[3]
    elif len(values) == 4:
        line['monto_otros_servicios'] = values[0]
        line['monto_uso_adicional'] = values[1]
        line['monto_creditos'] = values[2]
    elif len(values) == 3:
        line['monto_otros_servicios'] = values[0]
        line['monto_creditos'] = values[1]
    elif len(values) == 2:
        line['monto_renta_plan'] = values[0]
    elif len(values) == 1:
        line['monto_renta_plan'] = values[0]
    return line
