# Changelog — Gestión de Flota y Empleados (Odoo 19)

Todas las modificaciones del módulo son registradas en este archivo para mantener trazabilidad y control de versiones.

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
