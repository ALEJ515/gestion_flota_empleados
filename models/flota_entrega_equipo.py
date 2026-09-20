import base64
import logging

from odoo import models, fields, api, _

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
        help="Empleado al que se le entrega o recibe el equipo. Al seleccionarlo se autocompletan Ruta, Localidad, Teléfono de flota y Responsable."
    )
    fecha = fields.Date(string='Fecha', default=fields.Date.context_today, required=True, tracking=True)
    estado = fields.Selection([
        ('draft', 'Borrador'),
        ('confirmado', 'Confirmado'),
    ], string='Estado', default='draft', required=True, tracking=True, index=True)

    # --- DATOS ENTREGA (autocompletados desde el Empleado, editables) ---
    cargo = fields.Char(
        string='Cargo',
        tracking=True,
        help="Cargo del empleado. Se autocompleta desde su ficha en Flota Empleados al seleccionar el Empleado, "
             "pero puede editarse manualmente si es necesario."
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
    ruta_id = fields.Many2one('flota.ruta', string='Ruta', tracking=True)
    ubicacion_id = fields.Many2one('flota.ubicacion', string='Localidad', tracking=True)
    recibido_por = fields.Char(string='Recibido por (Responsable)', tracking=True)
    telefono_flota = fields.Char(string='Núm. de Teléfono (Flota)', tracking=True)

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

    @api.onchange('empleado_id')
    def _onchange_empleado_id(self):
        for rec in self:
            if rec.empleado_id:
                rec.ruta_id = rec.empleado_id.ruta_id
                rec.ubicacion_id = rec.empleado_id.ubicacion_id
                rec.telefono_flota = rec.empleado_id.numero_flota
                rec.recibido_por = rec.empleado_id.name
                rec.cargo = rec.empleado_id.cargo

    def _completar_datos_empleado(self, vals):
        """Si vals trae un nuevo empleado_id, autocompleta (con setdefault, sin pisar valores que
        ya vengan explícitos en el mismo vals) Ruta, Localidad, Teléfono de flota, Responsable y
        Cargo desde la ficha de ese empleado. Sirve de respaldo a nivel de servidor del onchange
        del formulario, para que estos datos queden siempre sincronizados con el Empleado
        seleccionado sin importar el origen de la escritura (formulario, importación, etc.)."""
        if vals.get('empleado_id'):
            empleado = self.env['flota.empleado'].browse(vals['empleado_id'])
            if empleado.exists():
                vals.setdefault('ruta_id', empleado.ruta_id.id)
                vals.setdefault('ubicacion_id', empleado.ubicacion_id.id)
                vals.setdefault('telefono_flota', empleado.numero_flota)
                vals.setdefault('recibido_por', empleado.name)
                vals.setdefault('cargo', empleado.cargo)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('flota.entrega.equipo') or _('Nuevo')
            self._completar_datos_empleado(vals)
        records = super().create(vals_list)
        records._guardar_qr_por_defecto()
        records._guardar_texto_aceptacion_por_defecto()
        return records

    def write(self, vals):
        if 'empleado_id' in vals:
            vals = self._completar_datos_empleado(dict(vals))
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
    marca = fields.Char(string='Marca')
    modelo = fields.Char(string='Modelo')
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
            self.marca = False
            self.estado_equipo = 'na'

    def _aplicar_regla_licencia(self, vals):
        """Fuerza Marca vacía y Estado 'N/A' cuando el Tipo de Equipo (ya sea el que viene en vals o el
        que ya tiene el registro) es una licencia. Se aplica también a nivel de servidor (create/write),
        no solo en el formulario, para que la regla sea consistente sin importar el origen del dato."""
        tipo_equipo_id = vals.get('tipo_equipo')
        tipo_equipo = self.env['flota.tipo.equipo'].browse(tipo_equipo_id) if tipo_equipo_id else self.tipo_equipo
        if tipo_equipo and tipo_equipo.es_licencia:
            vals['marca'] = False
            vals['estado_equipo'] = 'na'
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
