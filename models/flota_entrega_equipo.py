import base64
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from .phone_utils import whatsapp_url

_logger = logging.getLogger(__name__)

# Opciones de estado usadas para el equipo entregado, la flota devuelta y la impresora.
ESTADO_EQUIPO_SELECTION = [
    ('nuevo', 'Nuevo'),
    ('casi_nuevo', 'Casi nuevo'),
    ('usado_excelente', 'Usado - Excelente Estado'),
    ('buen_estado', 'Buen Estado'),
    ('usado', 'Usado'),
    ('prestado', 'Prestado'),
    ('averiado', 'Averiado / Dañado'),
    ('na', 'N/A'),
]

# Texto legal por defecto de la sección "Aceptación y responsabilidad" del PDF (editable por acta).
TEXTO_ACEPTACION_DEFAULT = (
    "Mediante la firma de este documento, comprendo y asumo la responsabilidad que me confiere "
    "la asignación de los equipos aquí detallados y entiendo que la violación a cualquiera de "
    "las directivas establecidas en la Política de Informática, la cual he recibido, leído y "
    "entendido, puede conllevar a que la empresa revoque mis privilegios y tome acciones "
    "disciplinarias y/o legales de acuerdo con lo establecido en dicha política."
)

# Tamaño de fuente (px) para cada opción de texto_aceptacion_tamano.
TEXTO_ACEPTACION_FONT_PX = {
    'pequeno': 12,
    'normal': 14,
    'grande': 17,
    'muy_grande': 20,
}

# Tamaño en px (ancho = alto, es cuadrado) para cada opción de qr_tamano.
QR_TAMANO_PX = {
    'pequeno': 110,
    'normal': 160,
    'grande': 210,
    'muy_grande': 260,
}


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
        domain="[('estado_asignacion', '=', 'asignada')]",
        help="Empleado al que se le entrega o recibe el equipo. No se pueden asociar actas a una línea "
             "que todavía esté disponible. Ruta, Localidad, Teléfono, Responsable "
             "y Cargo están vinculados a su perfil; al editarlos también se actualiza el empleado."
    )
    fecha = fields.Date(string='Fecha', default=fields.Date.context_today, required=True, tracking=True)
    estado = fields.Selection([
        ('draft', 'Borrador'),
        ('confirmado', 'Confirmado'),
    ], string='Estado', default='draft', required=True, tracking=True, index=True)

    # Datos compartidos con el empleado, también editables desde el acta.
    cargo = fields.Char(
        string='Cargo',
        related='empleado_id.cargo',
        store=True,
        readonly=False,
        tracking=True,
        help="Cargo vinculado al perfil del empleado. Editarlo actualiza su perfil y sus otras actas."
    )
    mostrar_ruta = fields.Boolean(
        string='Mostrar Ruta en el Documento',
        compute='_compute_mostrar_ruta',
        store=True,
        help="Se activa automáticamente cuando el Cargo corresponde a Vendedor o Distribuidor. Controla si la "
             "Ruta se imprime en el PDF del acta."
    )
    preparado_por_id = fields.Many2one(
        'res.users', string='Preparado por',
        default=lambda self: self.env.user, tracking=True
    )
    ruta_id = fields.Many2one(
        'flota.ruta', string='Ruta', related='empleado_id.ruta_id',
        store=True, readonly=False, tracking=True
    )
    ubicacion_id = fields.Many2one(
        'flota.ubicacion', string='Localidad', related='empleado_id.ubicacion_id',
        store=True, readonly=False, tracking=True
    )
    recibido_por = fields.Char(
        string='Recibido o Entregado Por', related='empleado_id.name',
        store=True, readonly=False, tracking=True,
        help="Nombre vinculado al empleado. Editarlo cambia su nombre en el perfil y en todas sus actas."
    )
    telefono_flota = fields.Char(
        string='Núm. de Teléfono (Flota)', related='empleado_id.numero_flota',
        store=True, readonly=False, tracking=True
    )

    # --- DATOS DE EQUIPO NUEVO ENTREGADO ---
    linea_ids = fields.One2many(
        'flota.entrega.equipo.linea', 'entrega_id',
        string='Equipos Entregados',
        domain=[('tipo_movimiento', '=', 'entregado')],
        context={'default_tipo_movimiento': 'entregado'},
    )
    cantidad_equipos = fields.Integer(string='Cantidad de Equipos', compute='_compute_cantidad_equipos', store=True)

    # --- EQUIPOS RECIBIDOS POR IT (DEVOLUCIÓN): equipo(s) antiguo(s) que el empleado devuelve, ya sea
    # flota (teléfono), laptop, monitor, UPS, impresora, o cualquier otro artículo del catálogo 'Equipo o
    # Licencias'. Puede haber varias líneas en una misma acta (ej. laptop + monitor + impresora + teléfono).
    linea_devuelta_ids = fields.One2many(
        'flota.entrega.equipo.linea', 'entrega_id',
        string='Equipos Recibidos por IT (Devolución)',
        domain=[('tipo_movimiento', '=', 'devuelto')],
        context={'default_tipo_movimiento': 'devuelto'},
        help="Equipos que el empleado devuelve/entrega de vuelta a IT (por ejemplo al ser desvinculado o al "
             "cambiar de equipo). No se limita a la flota: puede registrar cualquier equipo del catálogo "
             "'Equipo o Licencias' (laptop, monitor, UPS, impresora, teléfono, etc.) y agregar tantas líneas "
             "como artículos se reciban. Esta sección solo aparece en el PDF/Excel si tiene al menos una línea."
    )

    # --- FIRMAS (espacio para firma física, sin firma digital) Y POLÍTICA ---
    entregado_por = fields.Char(
        string='Firma Representante IT',
        default=lambda self: self.env.user.name,
        tracking=True,
        help="Nombre del representante de TI que entrega el equipo. Se imprime sobre la línea de firma "
             "'Firma Representante IT' para que la persona firme físicamente el documento."
    )
    recibio_politica = fields.Selection([
        ('si', 'Sí'),
        ('no', 'No'),
    ], string='¿Recibió la Política de Informática?', default='si', tracking=True)
    texto_aceptacion = fields.Text(
        string='Texto de Aceptación y Responsabilidad',
        default=lambda self: self.env['ir.config_parameter'].sudo().get_param(
            'gestion_flota_empleados.texto_aceptacion_default'
        ) or TEXTO_ACEPTACION_DEFAULT,
        help="Texto legal que se imprime en la sección 'Aceptación y responsabilidad' del PDF. Puede editarlo, "
             "ampliarlo o personalizarlo libremente; lo que escriba aquí es exactamente lo que saldrá en la "
             "hoja de entrega. Al guardar, este texto queda como predeterminado para las próximas actas nuevas."
    )
    texto_aceptacion_tamano = fields.Selection([
        ('pequeno', 'Pequeño'),
        ('normal', 'Normal'),
        ('grande', 'Grande'),
        ('muy_grande', 'Muy Grande'),
    ], string='Tamaño del Texto (Aceptación y Responsabilidad)', default='normal', tracking=True,
        help="Controla el tamaño de letra con el que se imprime el texto de Aceptación y Responsabilidad en el PDF."
    )
    texto_aceptacion_font_px = fields.Integer(
        string='Tamaño de Fuente (px)',
        compute='_compute_texto_aceptacion_font_px',
    )
    politica_url = fields.Char(
        string='Enlace a la Política de Informática',
        default=lambda self: self.env['ir.config_parameter'].sudo().get_param(
            'gestion_flota_empleados.politica_informatica_url', default=''
        ),
        help="URL de la política de informática. Se usa para generar el código QR del acta si no se sube una "
             "imagen propia. Puede configurarse de forma general en Ajustes Técnicos > Parámetros del Sistema "
             "con la clave 'gestion_flota_empleados.politica_informatica_url'."
    )
    politica_qr_imagen = fields.Image(
        string='Imagen del QR (opcional)',
        max_width=400, max_height=400,
        default=lambda self: self.env['ir.config_parameter'].sudo().get_param(
            'gestion_flota_empleados.politica_qr_imagen_default'
        ) or False,
        help="Suba aquí la foto/imagen del código QR de la política de informática tal como debe imprimirse. "
             "Una vez subida, queda guardada como QR predeterminado y se precargará automáticamente en las "
             "próximas actas nuevas para que no tenga que volver a subirla cada vez; puede reemplazarla cuando "
             "lo necesite. Si no sube ninguna imagen, el sistema genera automáticamente un QR a partir del "
             "enlace configurado."
    )
    politica_qr_final = fields.Binary(
        string='QR Política (para documentos)',
        compute='_compute_politica_qr_final',
        help="Imagen del QR realmente usada en el PDF y el Excel: la subida manualmente o, si no hay ninguna, "
             "una generada automáticamente a partir del enlace. Se calcula siempre en el servidor (no depende de "
             "una URL externa) para que salga de forma consistente en todas las actas."
    )
    mostrar_qr = fields.Boolean(
        string='Mostrar QR en el PDF', default=True, tracking=True,
        help="Desactive esta opción si no desea que el código QR de la política de informática salga impreso "
             "en el PDF del acta. La imagen sigue guardada aquí, solo se oculta en el documento."
    )
    qr_tamano = fields.Selection([
        ('pequeno', 'Pequeño'),
        ('normal', 'Normal'),
        ('grande', 'Grande'),
        ('muy_grande', 'Muy Grande'),
    ], string='Tamaño del QR', default='normal', tracking=True,
        help="Controla el tamaño con el que se imprime el código QR en el PDF."
    )
    qr_tamano_px = fields.Integer(
        string='Tamaño de QR (px)',
        compute='_compute_qr_tamano_px',
    )

    # --- CONTROL DOCUMENTAL DEL FORMATO (editable por si cambia la versión oficial) ---
    codigo_formulario = fields.Char(string='Código de Formulario', default='MS-TE-FO-001')
    version_formulario = fields.Char(string='Versión', default='3.00')

    notas = fields.Text(string='Notas')
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company)

    # --- REASIGNACIÓN A OTRO EMPLEADO: permite crear una acta nueva para un empleado distinto,
    # copiando los equipos (entregados y/o devueltos) de esta acta, sin tener que digitarlos de
    # nuevo. Típico caso de uso: el empleado titular se desvincula y su equipo pasa a su reemplazo.
    reasignado_de_id = fields.Many2one(
        'flota.entrega.equipo', string='Reasignada desde el Acta', readonly=True, copy=False, index=True, tracking=True,
        help="Indica que esta acta fue generada por reasignación de equipos desde otra acta (por ejemplo, al "
             "reemplazar a un empleado que se desvinculó)."
    )
    reasignada_a_ids = fields.One2many(
        'flota.entrega.equipo', 'reasignado_de_id', string='Actas Generadas por Reasignación'
    )
    reasignada_a_count = fields.Integer(
        string='Cantidad de Reasignaciones', compute='_compute_reasignada_a_count'
    )

    @api.depends('reasignada_a_ids')
    def _compute_reasignada_a_count(self):
        for rec in self:
            rec.reasignada_a_count = len(rec.reasignada_a_ids)

    @api.depends('linea_ids.cantidad')
    def _compute_cantidad_equipos(self):
        for rec in self:
            rec.cantidad_equipos = sum(rec.linea_ids.mapped('cantidad'))

    @api.depends('politica_qr_imagen', 'politica_url')
    def _compute_politica_qr_final(self):
        for rec in self:
            qr_bytes = rec._get_qr_image_bytes()
            rec.politica_qr_final = base64.b64encode(qr_bytes) if qr_bytes else False

    @api.depends('texto_aceptacion_tamano')
    def _compute_texto_aceptacion_font_px(self):
        for rec in self:
            rec.texto_aceptacion_font_px = TEXTO_ACEPTACION_FONT_PX.get(
                rec.texto_aceptacion_tamano, TEXTO_ACEPTACION_FONT_PX['normal']
            )

    @api.depends('qr_tamano')
    def _compute_qr_tamano_px(self):
        for rec in self:
            rec.qr_tamano_px = QR_TAMANO_PX.get(rec.qr_tamano, QR_TAMANO_PX['normal'])

    @api.depends('cargo')
    def _compute_mostrar_ruta(self):
        for rec in self:
            cargo = (rec.cargo or '').strip().lower()
            rec.mostrar_ruta = bool(cargo) and any(k in cargo for k in ('vendedor', 'distribuidor'))

    @api.constrains('empleado_id')
    def _check_empleado_asignado(self):
        for rec in self:
            if rec.empleado_id and rec.empleado_id.estado_asignacion != 'asignada':
                raise ValidationError(_(
                    'No se puede emitir un acta para una línea Disponible. Asigne primero el número a una persona.'
                ))

    def action_open_whatsapp(self):
        self.ensure_one()
        url = whatsapp_url(self.telefono_flota)
        if not url:
            raise UserError(_('Esta acta no tiene un número válido para abrir WhatsApp.'))
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    def action_reasignar_empleado(self):
        """Abre el asistente para reasignar los equipos de esta acta a otro empleado (por
        ejemplo, cuando el titular se desvincula y su reemplazo recibe el mismo equipo)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reasignar Equipos a Otro Empleado'),
            'res_model': 'flota.entrega.equipo.reasignar.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_entrega_id': self.id},
        }

    def action_ver_reasignaciones(self):
        """Abre la(s) acta(s) generadas por reasignación a partir de esta."""
        self.ensure_one()
        actas = self.reasignada_a_ids
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Actas Generadas por Reasignación'),
            'res_model': 'flota.entrega.equipo',
        }
        if len(actas) == 1:
            action.update({'view_mode': 'form', 'res_id': actas.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('id', 'in', actas.ids)]})
        return action

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('flota.entrega.equipo') or _('Nuevo')
        records = super().create(vals_list)
        records._guardar_qr_por_defecto()
        records._guardar_texto_aceptacion_por_defecto()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'politica_qr_imagen' in vals:
            self._guardar_qr_por_defecto()
        if 'texto_aceptacion' in vals:
            self._guardar_texto_aceptacion_por_defecto()
        return res

    def _guardar_qr_por_defecto(self):
        """Persiste la última imagen de QR subida como valor por defecto global (parámetro del
        sistema), para que no desaparezca al crear una nueva acta: cada acta nueva la traerá
        precargada automáticamente."""
        for rec in self:
            if rec.politica_qr_imagen:
                valor = rec.politica_qr_imagen
                if isinstance(valor, bytes):
                    valor = valor.decode('ascii')
                self.env['ir.config_parameter'].sudo().set_param(
                    'gestion_flota_empleados.politica_qr_imagen_default', valor
                )

    def _guardar_texto_aceptacion_por_defecto(self):
        """Persiste el último texto de Aceptación y Responsabilidad editado como valor por
        defecto global, para que las próximas actas nuevas lo traigan precargado."""
        for rec in self:
            if rec.texto_aceptacion:
                self.env['ir.config_parameter'].sudo().set_param(
                    'gestion_flota_empleados.texto_aceptacion_default', rec.texto_aceptacion
                )

    def action_descargar_pdf(self):
        """Descarga directamente el acta en PDF (reemplaza la antigua vista previa embebida)."""
        report = self.env.ref('gestion_flota_empleados.action_report_flota_entrega_equipo')
        return report.report_action(self)

    def action_confirmar(self):
        self.write({'estado': 'confirmado'})

    def action_restablecer_borrador(self):
        self.write({'estado': 'draft'})

    def _get_qr_image_bytes(self):
        """Devuelve los bytes PNG del QR de la política de informática: usa la imagen subida
        manualmente si existe, o genera una con el enlace configurado."""
        self.ensure_one()
        if self.politica_qr_imagen:
            return base64.b64decode(self.politica_qr_imagen)
        if self.politica_url:
            try:
                return self.env['ir.actions.report'].barcode('QR', self.politica_url, width=200, height=200)
            except Exception:
                _logger.exception("No se pudo generar el QR de la política para el acta %s", self.id)
        return False


class FlotaEntregaEquipoLinea(models.Model):
    _name = 'flota.entrega.equipo.linea'
    _description = 'Línea de Equipo Entregado'
    _order = 'id asc'

    entrega_id = fields.Many2one('flota.entrega.equipo', string='Acta de Entrega', required=True, ondelete='cascade', index=True)
    tipo_movimiento = fields.Selection([
        ('entregado', 'Entregado'),
        ('devuelto', 'Devuelto'),
    ], string='Movimiento', default='entregado', required=True, index=True,
        help="Indica si esta línea corresponde a un equipo entregado al empleado o a un equipo que el "
             "empleado devuelve a IT. Determina en qué sección del acta (Equipo Nuevo Entregado o Equipos "
             "Recibidos por IT) se muestra esta línea."
    )
    tipo_equipo = fields.Many2one(
        'flota.tipo.equipo',
        string='Tipo de Equipo',
        required=True,
        help="Seleccione el equipo o la licencia del catálogo 'Equipo o Licencias'. Si el que necesita no "
             "existe, puede crearlo directamente desde este campo. Si el registro elegido está marcado como "
             "'Es Licencia', no será necesario indicar Marca y el Estado quedará automáticamente en 'N/A'."
    )
    es_linea_licencia = fields.Boolean(
        related='tipo_equipo.es_licencia', store=True, string='Es Licencia',
        help="Se activa automáticamente cuando el Tipo de Equipo seleccionado está marcado como 'Es Licencia' "
             "en el catálogo 'Equipo o Licencias'. Controla si esta línea se muestra como equipo físico o "
             "como licencia."
    )
    marca_id = fields.Many2one(
        'flota.equipo.marca',
        string='Marca',
        ondelete='restrict',
        index=True,
        help="Marca del equipo seleccionable del catálogo de Marcas de Estructura y Recursos."
    )
    modelo_id = fields.Many2one(
        'flota.equipo.modelo',
        string='Modelo',
        ondelete='restrict',
        index=True,
        help="Modelo del equipo seleccionable del catálogo de Modelos (filtrado según la Marca seleccionada)."
    )
    marca = fields.Char(string='Marca (Texto)')
    modelo = fields.Char(string='Modelo (Texto)')
    cantidad = fields.Integer(string='Cant.', default=1, required=True)
    imei_serial = fields.Char(string='IMEI / Serial')
    estado_equipo = fields.Selection(ESTADO_EQUIPO_SELECTION, string='Estado', default='nuevo')
    observaciones = fields.Char(
        string='Estado / Observaciones',
        help="Ej. Protector de pantalla roto, cámara cristal roto, se friza a veces."
    )

    @api.onchange('tipo_equipo')
    def _onchange_tipo_equipo(self):
        """Si el Tipo de Equipo elegido es una licencia, no aplica Marca ni un Estado físico:
        se limpia Marca y el Estado pasa automáticamente a 'N/A'."""
        if self.tipo_equipo and self.tipo_equipo.es_licencia:
            self.marca_id = False
            self.modelo_id = False
            self.marca = False
            self.modelo = False
            self.estado_equipo = 'na'

    @api.onchange('marca_id')
    def _onchange_marca_id(self):
        for rec in self:
            if rec.marca_id:
                rec.marca = rec.marca_id.name
                if rec.modelo_id and rec.modelo_id.marca_id != rec.marca_id:
                    rec.modelo_id = False
                    rec.modelo = False

    @api.onchange('modelo_id')
    def _onchange_modelo_id(self):
        for rec in self:
            if rec.modelo_id:
                rec.modelo = rec.modelo_id.name
                if rec.modelo_id.marca_id and not rec.marca_id:
                    rec.marca_id = rec.modelo_id.marca_id
                    rec.marca = rec.modelo_id.marca_id.name

    def _aplicar_regla_licencia(self, vals):
        """Fuerza Marca vacía y Estado 'N/A' cuando el Tipo de Equipo (ya sea el que viene en vals o el
        que ya tiene el registro) es una licencia. Se aplica también a nivel de servidor (create/write),
        no solo en el formulario, para que la regla sea consistente sin importar el origen del dato."""
        tipo_equipo_id = vals.get('tipo_equipo')
        tipo_equipo = self.env['flota.tipo.equipo'].browse(tipo_equipo_id) if tipo_equipo_id else self.tipo_equipo
        if tipo_equipo and tipo_equipo.es_licencia:
            vals['marca_id'] = False
            vals['modelo_id'] = False
            vals['marca'] = False
            vals['modelo'] = False
            vals['estado_equipo'] = 'na'
        else:
            if 'marca_id' in vals and vals['marca_id']:
                marca_rec = self.env['flota.equipo.marca'].browse(vals['marca_id'])
                if marca_rec.exists():
                    vals.setdefault('marca', marca_rec.name)
            if 'modelo_id' in vals and vals['modelo_id']:
                modelo_rec = self.env['flota.equipo.modelo'].browse(vals['modelo_id'])
                if modelo_rec.exists():
                    vals.setdefault('modelo', modelo_rec.name)
                    if not vals.get('marca_id') and modelo_rec.marca_id:
                        vals.setdefault('marca_id', modelo_rec.marca_id.id)
                        vals.setdefault('marca', modelo_rec.marca_id.name)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._aplicar_regla_licencia(dict(vals)) for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        for rec in self:
            rec_vals = rec._aplicar_regla_licencia(dict(vals))
            super(FlotaEntregaEquipoLinea, rec).write(rec_vals)
        return True
