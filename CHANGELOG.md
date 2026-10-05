# Changelog — Gestión de Flota y Empleados (Odoo 19)

Todas las modificaciones del módulo son registradas en este archivo para mantener trazabilidad y control de versiones.

---

## [19.0.1.90.0] - 2026-10-05
### Nombres uniformes e importación sin distinguir mayúsculas
- Empleados, Departamentos, Subdepartamentos y Ubicaciones normalizan su nombre al crear o editar,
  también desde Excel/API: `  VENTAS   CANAL TRADICIONAL  ` pasa a `Ventas Canal Tradicional`.
  Se conservan acentos y las siglas IT, TI, UPS y CEDI.
- No se modifican códigos de rutas, códigos internos, modelos, marcas, IMEI, teléfonos ni correos.
- Las referencias por nombre al importar usan una clave exacta que ignora mayúsculas y espacios
  sobrantes. Así un Departamento en mayúsculas encuentra el registro existente sin crear otro.
- La búsqueda no interpreta `%` ni `_` como comodines. Si un nombre identifica varios registros
  (por ejemplo un subdepartamento repetido), se muestra un error y se debe importar por ID externo.
- Los nombres existentes no se renombrarán en bloque durante la actualización del módulo.
  Importar una referencia tampoco cambia el nombre del catálogo; editar o importar directamente
  la columna Nombre de ese registro sí aplica el formato uniforme.
- Mantener la columna ID en las plantillas de actualización sigue siendo la opción recomendada.

---

## [19.0.1.89.0] - 2026-10-05
### Subdepartamentos
- Nuevo catálogo en **Estructura y Recursos > Subdepartamentos**, también editable desde la pestaña
  **Subdepartamentos** de cada departamento. Cada división pertenece a un departamento y se puede archivar.
- Campo opcional **Subdepartamento** en el perfil, lista, tarjetas y compañeros de departamento.
  Los departamentos, consolidados de facturación y totales existentes mantienen su agrupación original.
- El panel izquierdo permite elegir Departamento y luego uno o varios Subdepartamentos de ese departamento,
  con contadores. Se incorporan búsqueda global, filtro **Sin Subdepartamento** y agrupación por división.
- Asignación Masiva permite asignar o retirar la división. Para empleados de distintos departamentos,
  se debe modificar también el Departamento o seleccionar empleados compatibles.
- Cambiar un departamento limpia las asignaciones anteriores que ya no correspondan. Una división
  explícita incompatible se rechaza, también por importación/API. No se puede mover una división a otro
  departamento mientras conserve empleados incompatibles, incluidos los archivados.
- Para Excel: crear primero las divisiones, exportar en modo compatible con importación con **ID**
  y **Subdepartamento**, editar e importar. Si un nombre se repite en varios departamentos, usar
  **Subdepartamento / ID** (ID externo) para identificar la división sin ambigüedad.
- Los empleados existentes quedan sin subdepartamento hasta su asignación; no se crean divisiones ni
  se reasignan empleados automáticamente. Se incluyen pruebas de reglas, importación y filtros.

---

## [19.0.1.88.0] - 2026-10-02
### Fechas de cambiazo y datos vinculados de las actas
- La lista de empleados muestra **Fecha Último Cambiazo** y distingue el **Estado Cambiazo (Calculado)**.
- Para actualizar fechas desde una plantilla: exportar **ID** y **Fecha Último Cambiazo**, conservar los IDs,
  escribir fechas como `2025-10-01` (AAAA-MM-DD) e importar mapeando esa columna a **Fecha Último Cambiazo**.
  Con Plan de Datos, las fechas de 12/18 meses y el estado se recalculan al guardar. Sin plan no aplica;
  sin fecha queda pendiente. Las columnas calculadas/facturación se pueden conservar y se ignoran al importar.
- Cargar la fecha desde una plantilla actualiza la referencia del conteo, pero no crea un evento de historial
  ni un acta. El botón **Registrar Cambiazo** sigue siendo la opción para registrar el evento completo.
- La columna Modelo y el PDF muestran solamente el nombre del modelo; Marca continúa en su propia columna.
- Nombre/responsable, cargo, ruta, localidad y teléfono del acta se vinculan al perfil del empleado.
  Los cambios en cualquiera de las dos pantallas se reflejan en las demás actas y en los PDF generados
  después, incluidas las actas confirmadas. No se modifican PDF ya descargados, equipos, firmas ni fechas.
- La actualización del módulo sincroniza las actas existentes con los datos vigentes del empleado.

---

## [v1.29.0] - 2026-09-05
### Corrección del Desglose por Empleado
- Se corrigieron las etiquetas para diferenciar renta del plan y otros servicios.
- Se conserva el total original de cada línea del PDF y se calcula su diferencia contra el total recalculado por Odoo.
- El financiamiento de equipos queda excluido de la base imponible automática.
- Se añadió el estado combinado de exceso de data y roaming.
- Las líneas de factura quedan protegidas contra edición fuera del estado Borrador.
- Las líneas sin consumo ahora se identifican por sus componentes, no solo por el total resultante.

---

## [v1.28.0] - 2026-09-05
### Eliminación de Integración n8n
- Se retiraron los endpoints HTTP públicos de sincronización.
- Se eliminó la configuración, menú y acciones de n8n.
- Se eliminó el paquete de controladores y la configuración de parámetros n8n.
- La conciliación de facturas continúa funcionando exclusivamente dentro de Odoo mediante procesamiento nativo de PDF.

---

## [v1.23.0 - Restauración a v1.4] - 2026-09-05
### Restauración a Versión v1.4 (Commit 33c7d07)
- **Motivo de Restauración**: Se revirtió la versión v1.5 que incrustaba un recuadro de mapeo visual de 8 columnas y rango de páginas (`page_start`/`page_end`) directamente dentro de la pestaña *Desglose por Empleado*.
- **Causa y Decisión**: El usuario verificó la interfaz en Odoo y prefirió no mantener controles de formulario/selectores dentro de la pestaña para no recargar la vista, solicitando regresar al estado previo v1.4.
- **Estado Técnico Vigente (v1.4)**:
  1. **Vista limpia de 7 columnas principales**: `Otros Servicio DM`, `Uso local DM`, `Llamadas larga distancia`, `Financiamiento`, `Otros cargos, créditos o descuentos`, `Imp`, `Total (RD$)`.
  2. **Extracción pos-teléfono (`post_phone_str`)**: Los montos se leen únicamente después del número para evitar corrimientos hacia roaming por texto/cálculos anteriores.
  3. **Tratamiento tributario correcto**: Los impuestos (30%) se aplican solo sobre servicios de telecomunicaciones, excluyendo cuotas de financiamiento de equipos.
  4. **Signos en créditos**: Valores con `CR` o `-` restan al total; valores positivos suman.
  5. **Columnas redundantes removidas**: Se retiraron `subtotal_linea`, `itbis_linea`, `cdt_linea` e `isc_linea` de la vista de la tabla.

---

## [v1.22.0] - 2026-09-05
### Refinamiento de Extracción y Validación por Fórmulas
- **Flexibilidad en Mapeo de Columnas**: Mapeo robusto para líneas de Claro con 6 o 7 columnas de consumo de forma dinámica.
- **Cálculo Exacto de Subtotal e Impuestos**: `subtotal_linea` recalcula la suma exacta de Renta, Otros Servicios, Uso Data, Roaming, Financiamiento y Créditos, aplicando de forma limpia la tasa impositiva del 30% de ley de República Dominicana.

---

## [v1.21.0] - 2026-09-05
### Corrección Crítica en Extracción de Líneas PDF Claro
- **Normalización de Columnas Concatenadas en PDF**: Corrección de patrones `0.00835.00` y `2,710.50809` donde el PDF concatenaba números sin espacios, causando que las líneas perdieran sus consumos de datos/planes y registraran totales negativos.
- **Precisión 100% en Suma de Líneas**: Las 259 líneas de empleados ahora suman exactamente `RD$307,652.80` de manera impecable.
- **Cuadre Perfecto Nivel Cuenta**: La conciliación `FAC-CLARO/2026/0017` fue reprocesada y ajustada exitosamente con un cuadro exacto a nivel de cuenta.

---

## [v1.20.0] - 2026-09-05
### Añadido y Mejorado
- **Optimización de Extracción PDF (PyPDF Prioritario)**: Extracción veloz de facturas PDF Claro en <1s evitando agotamiento de memoria del servidor (`UncaughtPromiseError`).
- **Fecha de Factura y Fecha de Subida**: Separación clara entre `fecha_factura` (Fecha emitida por Claro) y `fecha_subida` (Fecha/Hora de registro en el sistema). Extracción automática de fecha desde el PDF.
- **Ajuste Nivel Cuenta Directo en Rubros Generales**: Eliminación de líneas artificiales (`CUENTA-GLOBAL`) en la lista de empleados. El ajuste corporativo a nivel de contrato se aplica directamente en `otros_cargos_creditos` dentro de *Rubros Generales de Factura Claro*.
- **Selector de Columnas Opcionales (`optional="show" / optional="hide"`)**: Activación del menú de selección nativo de Odoo (3 puntos) en las tablas de conciliación de líneas para agregar o quitar cualquier columna disponible.

---

## [v1.19.0] - 2026-09-05
### Correcciones
- Normalización estricta de unicidad de flota y manifest bump.

---

## [v1.18.0] - 2026-09-04
### Añadido y Mejorado
- **Conciliación Financiera Nivel Cuenta vs. Líneas**: Campos `total_lineas_sum`, `diferencia_conciliacion` y `estado_cuadre` para diferenciar consumos de empleados vs. créditos/ajustes corporativos globales aplicados a nivel de contrato Claro.
- **Banner Informativo de Conciliación**: Bloque de alerta visual interactivo que explica la conciliación perfecta o la presencia de notas de crédito/ajustes corporativos a nivel de cuenta.
- **Botón de Ajuste Corporativo Nivel Cuenta (`CUENTA-GLOBAL`)**: Permite generar opcionalmente la línea de descuento/ajuste global para lograr un cuadre exacto al 100% con la factura de Claro.
- **KPIs Superiores Actualizados**: Tarjetas en tiempo real de Total Factura Claro, Suma Líneas Empleados, Ajuste Nivel Cuenta y Excesos Data/Roaming.

---

## [v1.17.0] - 2026-09-04
### Añadido y Mejorado
- **Limpieza de Duplicados en Base de Datos**: Desduplicación completa de empleados por nombre y número de flota.
- **Validación de Unicidad de Nombre y Teléfono**: Restricción SQL/Python `@api.constrains('numero_flota', 'name')` para impedir registros duplicados de nombres o teléfonos.
- **Creación Automática de Empleados para Nuevos Números**: Al conciliar un PDF con números no registrados, se crea automáticamente el perfil del empleado con nota indicando "Nuevo número registrado desde Factura Claro".
- **Indicador sutil de Tendencia de Consumo (▲ / ▼ / =)**: Comparativa automática entre la última facturación y la anterior con insignias en color (Azul=Nuevo cargo, Amarillo=Aumentó ▲, Verde=Disminuyó ▼, Gris=Sin variación).
- **Desglose Completo en Perfil del Empleado**: Pestaña "Historial de Consumo Telefónico" ampliada con todas las columnas configurables (Renta Plan, Otros Servicios, Uso Data/Voz, Roaming/LD, Financiamiento, Créditos, Subtotal, ITBIS 18%, CDT 2%, ISC 10%, Total Línea).
- **Sumas Totales Generales en Listas**: Inclusión de totales en el pie de tabla (`sum="..."`) para todas las columnas de la Conciliación de Facturas Claro.
- **Estado de Líneas con Monto $0 (`sin_consumo`)**: Distintivo visual especial (Celeste/Info) para números con RD$0 sin consumo, diferenciándolos del color rojo.

---

## [v1.16.0] - 2026-09-04
### Mejorado y Corregido
- **Sincronización Automática de Estado de Empleados (Activo vs Inactivo)**: Al realizar la conciliación de la factura de Claro, los empleados cuyos números estén presentes en la factura se mantienen o pasan a estado **Activo**. Los empleados registrados cuya flota NO aparezca en la factura pasan automáticamente a estado **Inactivo**.
- **Ampliación de Regex de Prefijos Telefónicos (809, 829, 849)**: Soporte completo para el código de área 849 y múltiples formatos (`1-849-XXX-XXXX`, `(809) XXX-XXXX`, etc.), asegurando un 100% de coincidencia y mapeo con la tabla de Empleados.
- **Normalización Multinivel en Mapeo de Empleados**: Búsqueda por 10 dígitos y 7 dígitos locales con `with_context(active_test=False)`.

---

## [v1.13.0] - 2026-09-03
### Añadido y Ajustado
- **Motor de Mapeo PDF Inteligente**: Diccionario de normalización telefónica en memoria que vincula al 100% los números de la factura con los Empleados.
- **Exportación Excel a 1 sola Hoja**: Exportación unificada en el orden exacto (Empleado, Número Flota, Cargo, Departamento, Total Línea) con el bloque de rubros de Claro al final de la misma hoja.
- **Depuración de n8n y Pivot**: Eliminación de menús y campos innecesarios de n8n y Pivot para simplificar la interfaz.
- **Ajuste de Etiquetas**: Renombrado a "Proveedor" y "Fecha".
- **Sin Emojis**: Eliminación total de emojis en textos e interfaz.

---

## [v1.9.0] - 2026-09-03
### Añadido
- **Extracción y Conciliación 100% NATIVA de PDF en Odoo (sin n8n)**:
  - Botón **"📄 Extraer y Conciliar PDF (Nativo)"** que lee directamente los bytes del archivo PDF con PyPDF2 / pdfplumber.
  - Regex avanzado nativo en Python para parsear rubros generales (Renta mensual, Renta otros servicios, Data Móvil, Roaming, Descuentos CR, ITBIS 18%, CDT 2%, ISC 10%, Total Mes).
  - Escaneo automático de números telefónicos (`809/829/849`) y vinculación directa con los Empleados, Departamentos y Ubicaciones de Odoo.
- **Exportación a Excel (`.xlsx`) y PDF Nativo QWeb**:
  - Descarga directa de reportes Excel multinoja e informe impreso en PDF.

---

## [v1.8.0] - 2026-09-03
### Añadido
- **Carga Directa de PDF en Odoo**:
  - Campo de adjunto `archivo_pdf` y botón **"⚡ Procesar PDF con n8n"** para enviar el PDF adjunto al flujo de parsing y conciliación automática.
- **Exportación a Excel (`.xlsx`)**:
  - Botón **"📊 Exportar a Excel (.xlsx)"** que genera un libro multinoja formateado con Resumen Claro, Consolidado por Departamento y Desglose por Empleado.
- **Reporte Imprimible PDF Nativo**:
  - Plantilla QWeb e informe corporativo **"Reporte Conciliación Factura Claro (PDF)"** listo para descarga e impresión oficial.

---

## [v1.7.0] - 2026-09-03
### Añadido
- **Centro de Conciliación Financiera Facturas Claro (`flota.factura.conciliacion` & `flota.factura.linea`)**:
  - Encabezado con rubros dinámicos de Claro: Renta Mensual, Renta Otros Servicios, Uso Data Móvil, Roaming y Otros Cargos/Créditos.
  - Cálculo automático de impuestos de República Dominicana: ITBIS (18%), CDT (2%), ISC (10%) y Subtotal / Total del Mes.
  - Desglose por Empleado/Línea con vinculación automática por `numero_flota` y detección de excesos de consumo.
  - Consolidación automática por Departamento / CEDI con porcentaje de gasto.
  - Tablero de KPIs en cabecera y Vistas Matriz Pivot / Gráficos por Departamento.
- **Endpoint API REST n8n (`/api/v1/flota/conciliar_factura`)**:
  - Permite a los workflows de n8n enviar la sabana de factura procesada para conciliación instantánea.

---

## [v1.6.0] - 2026-09-03
### Añadido
- **Asistente de Asignación Masiva (`flota.empleado.mass.update.wizard`)**:
  - Permite seleccionar múltiples empleados desde la vista lista y asignar en lote CEDI/Ubicación, Departamento, Cargo y Estado.
  - Integrado en el menú **Acciones** de la vista lista de Empleados.
  - Registra cambios en el Chatter de cada empleado y dispara webhooks a n8n si la sincronización automática está activa.
- **Logo del Módulo (`static/description/icon.png` e `icon.svg`)**:
  - Diseño vectorial profesional en tonos Dark Slate, Electric Blue, Cyan y Gold para el menú de Aplicaciones.

---

## [v1.5.0] - 2026-09-03
### Cambios
- Optimización de vistas kanban y tree.
- Configuración de logotipos y estilos CSS backend (`flota_style.css`).

---

## [v1.4.0] - 2026-09-03
### Añadido
- Botón centralizado de Sincronización n8n en Ajustes.
- Campo computado de Compañeros del mismo Departamento (`companeros_departamento_ids`).

---

## [v1.0.0] - 2026-08-30
### Inicial
- Creación inicial del módulo `gestion_flota_empleados`.
- Modelos `flota.empleado`, `flota.departamento`, `flota.ubicacion`.
- Integración básica n8n y auditoría en Chatter.
