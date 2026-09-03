import json
import logging
from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)

class FlotaEmpleadoController(http.Controller):

    def _validate_token(self):
        token = request.httprequest.headers.get('Authorization') or request.httprequest.args.get('token')
        ICP = request.env['ir.config_parameter'].sudo()
        config_token = ICP.get_param('gestion_flota_empleados.n8n_api_key')
        
        if config_token and token != f'Bearer {config_token}' and token != config_token:
            return False
        return True

    # ---------------------------------------------------------
    # ENDPOINTS EMPLEADOS & FLOTA
    # ---------------------------------------------------------
    @http.route('/api/v1/flota/empleados', type='jsonrpc', auth='none', methods=['POST', 'GET'], csrf=False)
    def get_empleados(self, **kwargs):
        """ Permite a n8n consultar la lista de empleados y flotas """
        if not self._validate_token():
            return {'error': 'No autorizado', 'code': 401}

        domain = [('active', '=', True)]
        empleados = request.env['flota.empleado'].sudo().search(domain)
        result = []
        for emp in empleados:
            result.append({
                'id': emp.id,
                'nombre': emp.name,
                'departamento': emp.departamento_id.name if emp.departamento_id else '',
                'ubicacion': emp.ubicacion_id.name if emp.ubicacion_id else '',
                'cargo': emp.cargo,
                'numero_flota': emp.numero_flota,
                'estado': emp.estado,
                'n8n_sync_status': emp.n8n_sync_status,
                'n8n_last_sync': fields.Datetime.to_string(emp.n8n_last_sync) if emp.n8n_last_sync else None
            })
        return {'status': 'success', 'data': result, 'count': len(result)}

    @http.route('/api/v1/flota/empleado/sync', type='jsonrpc', auth='none', methods=['POST', 'GET'], csrf=False)
    def sync_empleado_from_n8n(self, **kwargs):
        """ Permite a n8n crear o actualizar empleados remotamente """
        if not self._validate_token():
            return {'error': 'No autorizado', 'code': 401}

        data = request.jsonrequest or kwargs
        nombre = data.get('nombre')
        numero_flota = data.get('numero_flota')
        departamento_nombre = data.get('departamento')
        ubicacion_nombre = data.get('ubicacion')
        cargo = data.get('cargo', '')
        estado = data.get('estado', 'active')

        if not nombre or not numero_flota:
            return {'error': 'Los campos "nombre" y "numero_flota" son obligatorios.', 'code': 400}

        # Buscar o crear Departamento
        dept = False
        if departamento_nombre:
            dept = request.env['flota.departamento'].sudo().search([('name', '=ilike', departamento_nombre)], limit=1)
            if not dept:
                dept = request.env['flota.departamento'].sudo().create({'name': departamento_nombre})

        # Buscar o crear Ubicación
        ubi = False
        if ubicacion_nombre:
            ubi = request.env['flota.ubicacion'].sudo().search([('name', '=ilike', ubicacion_nombre)], limit=1)
            if not ubi:
                ubi = request.env['flota.ubicacion'].sudo().create({'name': ubicacion_nombre})

        # Buscar empleado por número de flota
        emp = request.env['flota.empleado'].sudo().search([('numero_flota', '=', numero_flota)], limit=1)
        vals = {
            'name': nombre,
            'cargo': cargo,
            'estado': estado,
            'n8n_sync_status': 'synced',
            'n8n_last_sync': fields.Datetime.now(),
            'n8n_response_log': 'Actualizado desde n8n via API JSON Endpoint'
        }
        if dept:
            vals['departamento_id'] = dept.id
        if ubi:
            vals['ubicacion_id'] = ubi.id

        if emp:
            emp.with_context(skip_n8n_sync=True).write(vals)
            action = 'updated'
        else:
            vals['numero_flota'] = numero_flota
            emp = request.env['flota.empleado'].sudo().with_context(skip_n8n_sync=True).create(vals)
            action = 'created'

        return {
            'status': 'success',
            'action': action,
            'empleado_id': emp.id,
            'nombre': emp.name,
            'numero_flota': emp.numero_flota,
            'departamento': emp.departamento_id.name if emp.departamento_id else '',
            'ubicacion': emp.ubicacion_id.name if emp.ubicacion_id else ''
        }

    # ---------------------------------------------------------
    # ENDPOINTS UBICACIONES (n8n CRUD)
    # ---------------------------------------------------------
    @http.route('/api/v1/flota/ubicaciones', type='jsonrpc', auth='none', methods=['POST', 'GET'], csrf=False)
    def get_ubicaciones(self, **kwargs):
        """ Permite a n8n listar todas las ubicaciones """
        if not self._validate_token():
            return {'error': 'No autorizado', 'code': 401}

        ubicaciones = request.env['flota.ubicacion'].sudo().search([('active', '=', True)])
        result = []
        for u in ubicaciones:
            result.append({
                'id': u.id,
                'nombre': u.name,
                'codigo': u.code or '',
                'total_empleados': u.total_empleados
            })
        return {'status': 'success', 'data': result, 'count': len(result)}

    @http.route('/api/v1/flota/ubicacion/sync', type='jsonrpc', auth='none', methods=['POST', 'GET'], csrf=False)
    def sync_ubicacion_from_n8n(self, **kwargs):
        """ Permite a n8n crear o actualizar ubicaciones directamente """
        if not self._validate_token():
            return {'error': 'No autorizado', 'code': 401}

        data = request.jsonrequest or kwargs
        nombre = data.get('nombre')
        codigo = data.get('codigo', '')
        active = data.get('active', True)

        if not nombre:
            return {'error': 'El campo "nombre" es obligatorio.', 'code': 400}

        ubi = request.env['flota.ubicacion'].sudo().search([('name', '=ilike', nombre)], limit=1)
        vals = {'name': nombre, 'code': codigo, 'active': active}
        if ubi:
            ubi.write(vals)
            action = 'updated'
        else:
            ubi = request.env['flota.ubicacion'].sudo().create(vals)
            action = 'created'

        return {
            'status': 'success',
            'action': action,
            'ubicacion_id': ubi.id,
            'nombre': ubi.name,
            'codigo': ubi.code
        }

    # ---------------------------------------------------------
    # ENDPOINTS DEPARTAMENTOS (n8n CRUD)
    # ---------------------------------------------------------
    @http.route('/api/v1/flota/departamentos', type='jsonrpc', auth='none', methods=['POST', 'GET'], csrf=False)
    def get_departamentos(self, **kwargs):
        """ Permite a n8n listar todos los departamentos """
        if not self._validate_token():
            return {'error': 'No autorizado', 'code': 401}

        departamentos = request.env['flota.departamento'].sudo().search([('active', '=', True)])
        result = []
        for d in departamentos:
            result.append({
                'id': d.id,
                'nombre': d.name,
                'codigo': d.code or '',
                'total_empleados': d.total_empleados
            })
        return {'status': 'success', 'data': result, 'count': len(result)}

    @http.route('/api/v1/flota/departamento/sync', type='jsonrpc', auth='none', methods=['POST', 'GET'], csrf=False)
    def sync_departamento_from_n8n(self, **kwargs):
        """ Permite a n8n crear o actualizar departamentos directamente """
        if not self._validate_token():
            return {'error': 'No autorizado', 'code': 401}

        data = request.jsonrequest or kwargs
        nombre = data.get('nombre')
        codigo = data.get('codigo', '')
        active = data.get('active', True)

        if not nombre:
            return {'error': 'El campo "nombre" es obligatorio.', 'code': 400}

        dept = request.env['flota.departamento'].sudo().search([('name', '=ilike', nombre)], limit=1)
        vals = {'name': nombre, 'code': codigo, 'active': active}
        if dept:
            dept.write(vals)
            action = 'updated'
        else:
            dept = request.env['flota.departamento'].sudo().create(vals)
            action = 'created'

        return {
            'status': 'success',
            'action': action,
            'departamento_id': dept.id,
            'nombre': dept.name,
            'codigo': dept.code
        }
