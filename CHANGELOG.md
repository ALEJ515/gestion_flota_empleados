# Changelog — Gestión de Flota y Empleados (Odoo 19)

Todas las modificaciones del módulo son registradas en este archivo para mantener trazabilidad y control de versiones.

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
