# Changelog — Gestión de Flota y Empleados (Odoo 19)

Todas las modificaciones del módulo son registradas en este archivo para mantener trazabilidad y control de versiones.

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
