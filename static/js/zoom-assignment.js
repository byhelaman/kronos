/**
 * Module to handle automatic Zoom meeting assignments
 */

import { TableComponent } from "./table-component.js";
import * as utils from "./utils.js";

class ZoomAssignmentManager {
    constructor() {
        this.modal = document.getElementById("zoom-assignment-modal");
        this.currentData = null;
        this.tableComponent = null;
        this.activeFilter = "all";
        // Guardar el último filtro activo antes de cerrar el modal
        this.lastActiveFilter = "all";
        // Almacenar selecciones por filtro (cada filtro tiene su propio Set de claves seleccionadas)
        this.filterSelections = {
            all: new Set(),
            to_update: new Set(),
            ok: new Set(),
            not_found: new Set(),
        };
        this.init();
    }

    init() {
        // Botón para abrir modal
        const btnAutoAssign = document.getElementById("btn-auto-assign");
        if (btnAutoAssign) {
            btnAutoAssign.addEventListener("click", () => this.openModal());
        }

        // Cerrar modal
        const closeButtons = this.modal.querySelectorAll("[data-modal-close]");
        closeButtons.forEach((btn) => {
            btn.addEventListener("click", () => this.closeModal());
        });

        // Filtros de tabs
        const filterTabs = this.modal.querySelectorAll(".filter-tab");
        filterTabs.forEach((tab) => {
            tab.addEventListener("click", () => this.switchFilter(tab.dataset.filter));
        });

        // Seleccionar todas - checkbox del header de la tabla
        const selectAllCheckbox = document.getElementById("select-all-checkbox");
        if (selectAllCheckbox) {
            selectAllCheckbox.addEventListener("change", (e) => {
                if (this.tableComponent) {
                    this.tableComponent.toggleSelectAll(e.target.checked);
                }
                // Sincronizar con la checkbox de filter-actions
                const filterCheckbox = document.getElementById("select-all-assignments");
                if (filterCheckbox) {
                    filterCheckbox.checked = e.target.checked;
                }
            });
        }

        // Seleccionar todas - checkbox de filter-actions
        const selectAllAssignments = document.getElementById("select-all-assignments");
        if (selectAllAssignments) {
            selectAllAssignments.addEventListener("change", (e) => {
                if (this.tableComponent) {
                    this.tableComponent.toggleSelectAll(e.target.checked);
                }
                // Sincronizar con la checkbox del header
                if (selectAllCheckbox) {
                    selectAllCheckbox.checked = e.target.checked;
                }
            });
        }

        // Botón ejecutar
        const btnExecute = document.getElementById("btn-execute-assignments");
        if (btnExecute) {
            btnExecute.addEventListener("click", () => this.executeAssignments());
        }

        // Botón sincronizar
        const btnSync = document.getElementById("btn-sync-zoom");
        if (btnSync) {
            btnSync.addEventListener("click", () => this.syncWithZoom());
        }

        // Menú contextual
        this.initContextMenu();

        // Cerrar con ESC
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && this.modal.classList.contains("is-open")) {
                this.closeModal();
            }
        });
    }

    initContextMenu() {
        const contextMenu = document.getElementById("assignment-context-menu");
        const copyRowAction = document.getElementById("copy-assignment-row-action");
        const deselectAllAction = document.getElementById("deselect-all-assignments-action");

        if (!contextMenu) return;

        // Copiar filas
        copyRowAction?.addEventListener("click", () => {
            if (this.tableComponent) {
                this.tableComponent.copySelectedRows();
            }
            contextMenu.style.display = "none";
        });

        // Deseleccionar todo
        deselectAllAction?.addEventListener("click", () => {
            if (this.tableComponent) {
                this.tableComponent.clearSelection();
            }
            contextMenu.style.display = "none";
        });
    }

    async openModal() {
        this.modal.classList.add("is-open");
        // Restaurar el último filtro activo antes de mostrar loading
        this.activeFilter = this.lastActiveFilter;
        this.showLoading();

        try {
            // Extraer datos del horario de la tabla
            const scheduleData = this.extractScheduleData();

            if (!scheduleData || scheduleData.length === 0) {
                this.showError("No schedule data to process.");
                return;
            }

            // Process assignments
            await this.processAssignments(scheduleData);
        } catch (error) {
            console.error("Error opening modal:", error);
            this.showError("Error processing schedule. Please try again.");
        }
    }

    isModalOpen() {
        return this.modal && this.modal.classList.contains("is-open");
    }

    async refreshModal() {
        if (!this.isModalOpen()) {
            return;
        }

        try {
            this.showLoading();
            // Extraer datos actualizados del horario de la tabla
            const scheduleData = this.extractScheduleData();

            if (!scheduleData || scheduleData.length === 0) {
                this.showError("No schedule data to process.");
                return;
            }

            // Process assignments con datos actualizados
            await this.processAssignments(scheduleData);
        } catch (error) {
            console.error("Error refreshing modal:", error);
            this.showError("Error refreshing schedule. Please try again.");
        }
    }

    extractScheduleData() {
        const table = document.getElementById("data-preview-table");
        if (!table) return [];

        const rows = table.querySelectorAll("tbody tr");
        const data = [];

        rows.forEach((row) => {
            // Solo extraer filas visibles (no eliminadas)
            if (row.style.display === "none") {
                return;
            }

            const cells = row.querySelectorAll("td");
            if (cells.length < 12) return; // Validar que tenga suficientes columnas

            // Extract Group (column 9, index 9) and Instructor (column 8, index 8)
            const group = cells[9]?.textContent?.trim() || "";
            const instructor = cells[8]?.textContent?.trim() || "";

            if (group && instructor) {
                data.push({
                    Group: group,
                    Instructor: instructor,
                });
            }
        });

        return data;
    }

    async processAssignments(scheduleData) {
        try {
            const response = await fetch("/zoom/assignments/process-from-schedule", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    schedule_rows: scheduleData,
                }),
            });

            const result = await response.json();

            if (!response.ok) {
                if (result.requires_sync) {
                    this.showSyncError();
                } else {
                    this.showError(result.error || "Error al procesar asignaciones");
                }
                return;
            }

            this.currentData = result;
            this.renderResults(result);
        } catch (error) {
            console.error("Error processing assignments:", error);
            this.showError("Connection error. Please try again.");
        }
    }

    renderResults(data) {
        this.hideAllSections();

        // Actualizar estadísticas en el footer
        document.getElementById("stat-total").textContent = data.summary.total;
        document.getElementById("stat-ok").textContent = data.summary.ok;
        document.getElementById("stat-update").textContent = data.summary.to_update;
        document.getElementById("stat-not-found").textContent = data.summary.not_found;

        if (data.summary.total === 0) {
            document.getElementById("modal-empty").style.display = "block";
            return;
        }

        // Show filters and table
        document.getElementById("modal-filters").style.display = "block";
        document.getElementById("modal-results").style.display = "block";
        document.getElementById("modal-footer").style.display = "flex";

        // Render table primero (necesita los datos para aplicar el filtro)
        this.renderTable(data);

        // Restaurar el filtro activo y aplicar el switchFilter para actualizar la vista
        // Esto asegura que el tab visual esté activo y la tabla se filtre correctamente
        this.switchFilter(this.activeFilter);

        // Update execute button
        this.updateExecuteButton();
    }

    renderTable(data) {
        const tbody = document.getElementById("assignment-table-body");
        tbody.innerHTML = "";

        // Preparar datos para el componente de tabla
        const tableData = [];

        // Render "to_update"
        data.to_update?.forEach((item) => {
            tableData.push({
                ...item,
                status: "to_update",
                canSelect: true,
            });
        });

        // Render "ok"
        data.ok?.forEach((item) => {
            tableData.push({
                ...item,
                status: "ok",
                canSelect: false,
            });
        });

        // Render "not_found"
        data.not_found?.forEach((item) => {
            tableData.push({
                ...item,
                status: "not_found",
                canSelect: false,
            });
        });

        // Función para renderizar una fila
        const rowRenderer = (item) => {
            const row = document.createElement("tr");
            row.className = `assignment-row assignment-row--${item.status}`;
            row.dataset.status = item.status;
            row.dataset.meetingId = item.meeting_id || "";
            row.dataset.instructorEmail = item.instructor_email || "";

            const statusLabels = {
                to_update: 'To Update',
                ok: 'Assigned',
                not_found: 'Not Found',
            };

            const checkbox = item.canSelect
                ? `<input type="checkbox" class="assignment-checkbox" data-meeting-id="${item.meeting_id}" data-instructor-email="${item.instructor_email}" />`
                : "";

            // Convertir Meeting ID en enlace si existe
            const meetingIdCell = item.meeting_id
                ? `<a href="https://zoom.us/meeting/${item.meeting_id}" target="_blank" rel="noopener noreferrer" class="meeting-link">${item.meeting_id}</a>`
                : "-";

            row.innerHTML = `
                <td>${checkbox}</td>
                <td>${statusLabels[item.status] || ""}</td>
                <td>${meetingIdCell}</td>
                <td>${item.meeting_topic || item.group || "-"}</td>
                <td>${item.instructor_name || item.instructor || "-"}</td>
                <td>${item.reason || "-"}</td>
            `;

            return row;
        };

        // Función para extraer clave única
        const rowKeyExtractor = (item) => {
            return `${item.meeting_id}:${item.instructor_email}`;
        };

        // Función para determinar si una fila puede ser seleccionada
        const canSelectRow = (item) => {
            return item.canSelect === true;
        };

        // Función para extraer clases CSS
        const rowClassExtractor = (item) => {
            return `assignment-row--${item.status}`;
        };

        // Función de filtro
        const filterFunction = (item) => {
            if (this.activeFilter === "all") {
                return true;
            }
            return item.status === this.activeFilter;
        };

        // Función para copiar filas
        const onCopyRows = (selectedRows) => {
            if (selectedRows.length === 0) {
                if (window.notificationManager) {
                    window.notificationManager.warning("No rows selected to copy.");
                }
                return false;
            }

            try {
                const textToCopy = selectedRows
                    .map((item) => {
                        const meetingId = item.meeting_id || "-";
                        const topic = item.meeting_topic || item.group || "-";
                        const instructor = item.instructor_name || item.instructor || "-";
                        const status = item.status === "to_update" ? "To Update" :
                            item.status === "ok" ? "Assigned" :
                                item.status === "not_found" ? "Not Found" : "";
                        const reason = item.reason || "-";

                        return `${meetingId}\n${topic}\n${instructor}\n${status}\n${reason}`;
                    })
                    .join("\n\n");

                navigator.clipboard
                    .writeText(textToCopy)
                    .then(() => {
                        if (window.notificationManager) {
                            const s = selectedRows.length > 1 ? "s" : "";
                            window.notificationManager.success(`Copied ${selectedRows.length} row${s}`);
                        }
                    })
                    .catch((err) => {
                        console.error("Error copying selected rows: ", err);
                        if (window.notificationManager) {
                            window.notificationManager.error("Error: Could not copy selected rows.");
                        }
                    });
                return true;
            } catch (err) {
                console.error("Error during copy formatting:", err);
                if (window.notificationManager) {
                    window.notificationManager.error("Error: Could not format data for copying.");
                }
                return false;
            }
        };

        // Callback cuando cambia la selección
        const onSelectionChange = (selectedRows, selectedCount) => {
            // Sincronizar las selecciones actuales con el filtro activo
            if (this.tableComponent) {
                this.filterSelections[this.activeFilter] = new Set(this.tableComponent.selectedRows);
            }
            this.updateExecuteButton();
            this.updateSelectAllCheckboxes();
        };

        // Callback cuando se muestra el menú contextual
        const onContextMenu = (rowData, e) => {
            // Prevenir el menú contextual en filtros "ok" y "not_found"
            const isNonSelectableFilter = this.activeFilter === "ok" || this.activeFilter === "not_found";
            if (isNonSelectableFilter) {
                // Retornar false para cancelar el menú
                return false;
            }

            // Actualizar estado del botón "Deselect all" según el filtro activo
            const deselectAllAction = document.getElementById("deselect-all-assignments-action");
            if (deselectAllAction) {
                deselectAllAction.disabled = false;
            }

            // Retornar true (o undefined) para permitir el menú
            return true;
        };

        // Configurar columnas ordenables desde los headers HTML
        const table = document.getElementById("assignment-preview-table");
        const headers = table ? Array.from(table.querySelectorAll("thead th")) : [];

        // Mapear nombres de columnas a propiedades de datos
        const columnNameMap = {
            "Status": "status",
            "Meeting ID": "meeting_id",
            "Meeting Topic": "meeting_topic",
            "Instructor": "instructor_name",
            "Reason": "reason",
        };

        // Configurar columnas ordenables
        const columnsConfig = headers.map((th, idx) => {
            const label = th.textContent.trim();
            let sortable = idx > 0; // Por defecto, todas excepto la primera son ordenables

            // Leer atributo data-sortable si existe
            if (th.hasAttribute("data-sortable")) {
                const sortableAttr = th.getAttribute("data-sortable");
                sortable = sortableAttr !== "false";
            }

            // Determinar parser según el tipo de columna
            let parser = utils.textParser;
            if (/id/i.test(label)) {
                parser = (s) => {
                    const num = parseInt(s, 10);
                    return isNaN(num) ? s : num;
                };
            }

            return {
                label: label,
                key: columnNameMap[label] || label.toLowerCase().replace(/\s+/g, "_"),
                index: idx,
                parser: parser,
                sortable: sortable,
                headerEl: th,
            };
        });

        // Función de ordenamiento personalizada
        const sortFunction = (a, b, criterion) => {
            const column = columnsConfig.find((c) => c.label === criterion.label);
            if (!column) return 0;

            let aValue, bValue;

            // Manejar casos especiales
            if (criterion.label === "Status") {
                // Mapear valores internos a valores mostrados para ordenar correctamente
                const statusMap = {
                    "to_update": "To Update",
                    "ok": "Assigned",
                    "not_found": "Not Found"
                };
                aValue = statusMap[a.status] || a.status || "";
                bValue = statusMap[b.status] || b.status || "";
            } else if (criterion.label === "Meeting Topic") {
                // Usar meeting_topic o group como fallback, asegurándose de obtener el valor correcto
                aValue = (a.meeting_topic || a.group || "").toString().trim();
                bValue = (b.meeting_topic || b.group || "").toString().trim();
            } else {
                // Obtener valores usando el mapeo de columnas
                // Intentar primero con column.key, luego con el nombre de la columna en diferentes formatos
                aValue = a[column.key] ||
                    a[column.label] ||
                    a[column.label.toLowerCase().replace(/\s+/g, "_")] ||
                    "";
                bValue = b[column.key] ||
                    b[column.label] ||
                    b[column.label.toLowerCase().replace(/\s+/g, "_")] ||
                    "";
            }

            const va = column.parser(String(aValue));
            const vb = column.parser(String(bValue));

            return va < vb ? -1 : va > vb ? 1 : 0;
        };

        // Función para actualizar indicadores visuales de ordenamiento
        const updateSortHeaders = () => {
            if (!this.tableComponent) return;

            // Primero, limpiar todas las flechas de todas las columnas
            columnsConfig.forEach((col) => {
                if (col.sortable && col.headerEl) {
                    const originalText = col.headerEl.dataset.originalText || col.label;

                    // Si hay checkbox, preservarlo y actualizar solo el texto
                    const checkbox = col.headerEl.querySelector("input[type='checkbox']");
                    if (checkbox) {
                        // Buscar o crear el span de texto
                        let textSpan = col.headerEl.querySelector("span");
                        if (!textSpan) {
                            textSpan = document.createElement("span");
                            col.headerEl.appendChild(textSpan);
                        }
                        // Limpiar cualquier flecha existente y establecer solo el texto original
                        textSpan.textContent = originalText.replace(/ [↑↓]$/, "");
                    } else {
                        // Si no hay checkbox, limpiar cualquier flecha existente
                        col.headerEl.textContent = originalText.replace(/ [↑↓]$/, "");
                    }
                }
            });

            // Luego, añadir flechas solo a las columnas ordenadas
            this.tableComponent.sortCriteria?.forEach((sc) => {
                const col = columnsConfig.find((c) => c.label === sc.label);
                if (col && col.headerEl) {
                    const originalText = col.headerEl.dataset.originalText || col.label;
                    const arrow = sc.direction === "asc" ? " ↑" : " ↓";

                    const checkbox = col.headerEl.querySelector("input[type='checkbox']");
                    if (checkbox) {
                        // Si hay checkbox, actualizar el texto después del checkbox
                        let textSpan = col.headerEl.querySelector("span");
                        if (!textSpan) {
                            textSpan = document.createElement("span");
                            col.headerEl.appendChild(textSpan);
                        }
                        // Asegurarse de que no haya flechas duplicadas
                        textSpan.textContent = originalText.replace(/ [↑↓]$/, "") + arrow;
                    } else {
                        // Asegurarse de que no haya flechas duplicadas
                        col.headerEl.textContent = originalText.replace(/ [↑↓]$/, "") + arrow;
                    }
                }
            });
        };

        // Configurar eventos de ordenamiento en los headers
        const initSorting = () => {
            columnsConfig.forEach((col) => {
                if (col.sortable && col.headerEl) {
                    col.headerEl.style.cursor = "pointer";

                    // Remover handler anterior si existe
                    if (col.headerEl._sortHandler) {
                        col.headerEl.removeEventListener("click", col.headerEl._sortHandler);
                        delete col.headerEl._sortHandler;
                    }

                    // Crear nuevo handler
                    const handler = (e) => {
                        // No ordenar si se hace clic en el checkbox o input
                        if (e.target.tagName === "INPUT" || e.target.type === "checkbox") return;

                        // Obtener criterio actual
                        const currentCriteria = this.tableComponent?.sortCriteria || [];
                        const existingIndex = currentCriteria.findIndex(
                            (sc) => sc.label === col.label
                        );
                        const isExisting = existingIndex > -1;

                        let newCriteria = [...currentCriteria];

                        // Ctrl/Cmd + Click: Remover filtro de criterios múltiples
                        if (e.ctrlKey || e.metaKey) {
                            if (isExisting) {
                                newCriteria.splice(existingIndex, 1);
                            }
                        }
                        // Shift + Click: Añadir a criterios múltiples (o cambiar dirección si ya existe)
                        else if (e.shiftKey) {
                            if (isExisting) {
                                newCriteria[existingIndex].direction =
                                    newCriteria[existingIndex].direction === "asc" ? "desc" : "asc";
                            } else {
                                newCriteria.push({ label: col.label, direction: "asc" });
                            }
                        }
                        // Click simple: Ciclo entre asc → desc → desactivar
                        else {
                            if (isExisting && newCriteria.length === 1) {
                                // Si ya está ordenada y es la única, ciclo: asc → desc → desactivar
                                if (newCriteria[0].direction === "asc") {
                                    newCriteria[0].direction = "desc";
                                } else {
                                    // Desactivar: remover el criterio
                                    newCriteria = [];
                                }
                            } else if (isExisting && newCriteria.length > 1) {
                                // Si hay múltiples criterios, cambiar solo esta columna a la siguiente dirección o remover
                                if (newCriteria[existingIndex].direction === "asc") {
                                    newCriteria[existingIndex].direction = "desc";
                                } else {
                                    // Remover este criterio específico
                                    newCriteria.splice(existingIndex, 1);
                                }
                            } else {
                                // Si no está ordenada, empezar con asc
                                newCriteria = [{ label: col.label, direction: "asc" }];
                            }
                        }

                        // Actualizar criterios de ordenamiento
                        if (this.tableComponent) {
                            this.tableComponent.setSortCriteria(newCriteria);
                        }

                        // Actualizar indicadores visuales
                        updateSortHeaders();
                    };

                    // Agregar el nuevo handler
                    col.headerEl.addEventListener("click", handler);
                    col.headerEl._sortHandler = handler;
                }
            });
        };

        // Inicializar headers para ordenamiento
        headers.forEach((th) => {
            // Limpiar cualquier flecha existente antes de guardar el texto original
            const cleanText = th.textContent.trim().replace(/ [↑↓]$/, "");
            th.dataset.originalText = cleanText;
        });

        // Crear o actualizar componente de tabla
        if (!this.tableComponent) {
            this.tableComponent = new TableComponent({
                tableSelector: "#assignment-preview-table",
                tbodySelector: "#assignment-table-body",
                selectAllCheckboxSelector: "#select-all-checkbox",
                contextMenuSelector: "#assignment-context-menu",
                copyRowActionSelector: "#copy-assignment-row-action",
                rowClass: "assignment-row",
                selectedRowClass: "assignment-row--selected",
                columns: columnsConfig,
                rowKeyExtractor,
                rowClassExtractor,
                canSelectRow,
                getRowCheckbox: (row) => row.querySelector(".assignment-checkbox"),
                filterFunction,
                sortFunction,
                onCopyRows,
                onSelectionChange,
                onContextMenu,
                noDataMessage: "No assignments found",
            });

            // Guardar referencia para actualizar headers
            this.updateSortHeaders = updateSortHeaders;

            // Asegurarse de que no hay criterios de ordenamiento previos
            this.tableComponent.setSortCriteria([]);

            // Inicializar ordenamiento
            initSorting();
        } else {
            // Actualizar configuración
            this.tableComponent.config.filterFunction = filterFunction;
            this.tableComponent.config.sortFunction = sortFunction;
            this.tableComponent.config.columns = columnsConfig;

            // Limpiar criterios de ordenamiento previos para evitar conflictos
            this.tableComponent.setSortCriteria([]);

            // Reinicializar headers para ordenamiento (limpiar flechas existentes)
            headers.forEach((th) => {
                const cleanText = th.textContent.trim().replace(/ [↑↓]$/, "");
                th.dataset.originalText = cleanText;
            });

            // Reinicializar ordenamiento con nueva configuración
            initSorting();

            // Actualizar indicadores visuales después de reinicializar
            updateSortHeaders();
        }

        // Renderizar filas
        const rows = tableData.map(item => {
            const row = rowRenderer(item);
            const key = rowKeyExtractor(item);
            // Restaurar selección del filtro activo si existe
            const wasSelected = this.filterSelections[this.activeFilter].has(key);
            return {
                data: item,
                row,
                key,
                visible: filterFunction(item),
                selected: wasSelected,
            };
        });

        // Limpiar selecciones de filas que ya no existen en los nuevos datos
        const existingKeys = new Set(rows.map(r => r.key));
        Object.keys(this.filterSelections).forEach(filterKey => {
            const selections = this.filterSelections[filterKey];
            const keysToRemove = Array.from(selections).filter(key => !existingKeys.has(key));
            keysToRemove.forEach(key => selections.delete(key));
        });

        this.tableComponent.rowsData = rows;
        // Restaurar selecciones del filtro activo (solo las que existen en los nuevos datos)
        const validSelections = Array.from(this.filterSelections[this.activeFilter]).filter(key => existingKeys.has(key));
        this.tableComponent.selectedRows = new Set(validSelections);

        // Asegurarse de que los criterios de ordenamiento estén limpios antes de renderizar
        // Esto evita que se mantenga el ordenamiento de la tabla principal
        if (this.tableComponent.sortCriteria && this.tableComponent.sortCriteria.length > 0) {
            // Solo mantener los criterios si son válidos para las columnas del modal
            const validCriteria = this.tableComponent.sortCriteria.filter(sc => {
                return columnsConfig.some(col => col.label === sc.label);
            });
            this.tableComponent.setSortCriteria(validCriteria);
        } else {
            this.tableComponent.setSortCriteria([]);
        }

        this.tableComponent.render();
    }

    updateExecuteButton() {
        const btnExecute = document.getElementById("btn-execute-assignments");
        if (!btnExecute || !this.tableComponent) return;

        const count = this.tableComponent.getSelectedRowCount();
        btnExecute.disabled = count === 0;

        if (count > 0) {
            btnExecute.querySelector(".btn-text").textContent = `Execute (${count})`;
        } else {
            btnExecute.querySelector(".btn-text").textContent = "Execute";
        }
    }

    switchFilter(filter) {
        // Guardar las selecciones actuales del filtro anterior
        if (this.tableComponent) {
            this.filterSelections[this.activeFilter] = new Set(this.tableComponent.selectedRows);
        }

        // Cambiar al nuevo filtro
        this.activeFilter = filter;
        // Actualizar también el último filtro activo para que se mantenga al cerrar/abrir el modal
        this.lastActiveFilter = filter;

        // Update active tabs
        document.querySelectorAll(".filter-tab").forEach((tab) => {
            tab.classList.toggle("active", tab.dataset.filter === filter);
        });

        // Mostrar/ocultar filter-actions solo cuando el filtro es "all"
        const filterActions = document.getElementById("filter-actions");
        if (filterActions) {
            filterActions.style.display = filter === "all" ? "flex" : "none";
        }

        // Deshabilitar select-all-checkbox en filtros donde no hay filas seleccionables
        const selectAllCheckbox = document.getElementById("select-all-checkbox");
        if (selectAllCheckbox) {
            const isNonSelectableFilter = filter === "ok" || filter === "not_found";
            selectAllCheckbox.disabled = isNonSelectableFilter;
            if (isNonSelectableFilter) {
                selectAllCheckbox.checked = false;
                selectAllCheckbox.indeterminate = false;
            }
        }

        // Deshabilitar botón "Deselect all" en el menú contextual para filtros no seleccionables
        const deselectAllAction = document.getElementById("deselect-all-assignments-action");
        if (deselectAllAction) {
            const isNonSelectableFilter = filter === "ok" || filter === "not_found";
            deselectAllAction.disabled = isNonSelectableFilter;
        }

        // Actualizar función de filtro del componente
        if (this.tableComponent) {
            // Restaurar las selecciones del nuevo filtro
            this.tableComponent.selectedRows = new Set(this.filterSelections[filter]);

            // Actualizar el estado selected de cada fila según las selecciones guardadas
            this.tableComponent.rowsData.forEach(rowItem => {
                const wasSelected = this.filterSelections[filter].has(rowItem.key);
                rowItem.selected = wasSelected;

                // Actualizar el checkbox visual
                const checkbox = this.tableComponent.config.getRowCheckbox(rowItem.row);
                if (checkbox) {
                    checkbox.checked = wasSelected;
                }

                // Actualizar clases CSS
                if (wasSelected) {
                    rowItem.row.classList.add(this.tableComponent.config.selectedRowClass);
                } else {
                    rowItem.row.classList.remove(this.tableComponent.config.selectedRowClass);
                }
            });

            this.tableComponent.config.filterFunction = (item) => {
                if (filter === "all") {
                    return true;
                }
                return item.status === filter;
            };
            this.tableComponent.render();
        }

        // Actualizar estado de las checkboxes según las filas visibles
        this.updateExecuteButton();
        this.updateSelectAllCheckboxes();
    }

    updateSelectAllCheckboxes() {
        if (!this.tableComponent) return;

        const visibleRows = this.tableComponent.rowsData.filter(row => row.visible);
        const selectableRows = visibleRows.filter(row =>
            this.tableComponent.config.canSelectRow(row.data, row.row)
        );
        const selectedVisible = selectableRows.filter(row => row.selected);

        const allChecked = selectableRows.length > 0 && selectedVisible.length === selectableRows.length;
        const someChecked = selectedVisible.length > 0 && selectedVisible.length < selectableRows.length;

        const selectAllCheckbox = document.getElementById("select-all-checkbox");
        const selectAllAssignments = document.getElementById("select-all-assignments");

        if (selectAllCheckbox) {
            selectAllCheckbox.checked = allChecked;
            selectAllCheckbox.indeterminate = someChecked;
        }
        if (selectAllAssignments) {
            selectAllAssignments.checked = allChecked;
            selectAllAssignments.indeterminate = someChecked;
        }
    }

    async executeAssignments() {
        if (!this.tableComponent) return;

        const selectedRows = this.tableComponent.getSelectedRows();
        if (selectedRows.length === 0) return;

        const btnExecute = document.getElementById("btn-execute-assignments");
        const btnCancel = this.modal.querySelector('.footer-actions .btn--secondary[data-modal-close]');

        btnExecute.disabled = true;
        btnExecute.classList.add("is-loading");
        if (btnCancel) {
            btnCancel.disabled = true;
        }

        try {
            // Convert selected to assignment format
            const assignments = selectedRows.map((item) => {
                return {
                    meeting_id: item.meeting_id,
                    instructor_email: item.instructor_email,
                };
            });

            const response = await fetch("/zoom/assignments/execute", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    assignments: assignments,
                }),
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.error || "Error executing assignments");
            }

            // Show result
            if (window.notificationManager) {
                window.notificationManager.success(
                    `Assignments completed: ${result.stats.success} successful, ${result.stats.errors} errors`
                );
            }

            // Close modal and reload
            this.closeModal();
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        } catch (error) {
            console.error("Error executing assignments:", error);
            if (window.notificationManager) {
                window.notificationManager.error(error.message || "Error executing assignments");
            }
        } finally {
            btnExecute.disabled = false;
            btnExecute.classList.remove("is-loading");
            if (btnCancel) {
                btnCancel.disabled = false;
            }
        }
    }

    async syncWithZoom() {
        const btnSync = document.getElementById("btn-sync-zoom");
        btnSync.disabled = true;
        btnSync.textContent = "Syncing...";

        try {
            const formData = new FormData();
            formData.append("force", "true");

            const response = await fetch("/zoom/sync", {
                method: "POST",
                body: formData,
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.detail || "Error syncing");
            }

            if (window.notificationManager) {
                window.notificationManager.success("Sync completed");
            }

            // Reprocess assignments
            const scheduleData = this.extractScheduleData();
            await this.processAssignments(scheduleData);
        } catch (error) {
            console.error("Error syncing:", error);
            if (window.notificationManager) {
                window.notificationManager.error(error.message || "Error syncing with Zoom");
            }
        } finally {
            btnSync.disabled = false;
            btnSync.textContent = "Sync with Zoom";
        }
    }

    showLoading() {
        this.hideAllSections();
        document.getElementById("modal-loading").style.display = "block";
    }

    showSyncError() {
        this.hideAllSections();
        document.getElementById("modal-sync-error").style.display = "block";
    }

    showError(message) {
        this.hideAllSections();

        // Eliminar cualquier elemento de error existente
        const modalBody = document.querySelector(".modal-body");
        const existingErrors = modalBody.querySelectorAll(".modal-alert--error");
        existingErrors.forEach(error => error.remove());

        const errorDiv = document.createElement("div");
        errorDiv.className = "modal-alert modal-alert--error";
        errorDiv.innerHTML = `<p>${message}</p>`;
        modalBody.appendChild(errorDiv);
    }

    hideAllSections() {
        document.getElementById("modal-loading").style.display = "none";
        document.getElementById("modal-sync-error").style.display = "none";
        document.getElementById("modal-filters").style.display = "none";
        document.getElementById("modal-results").style.display = "none";
        document.getElementById("modal-empty").style.display = "none";
        document.getElementById("modal-footer").style.display = "none";

        // Eliminar elementos de error dinámicos
        const modalBody = document.querySelector(".modal-body");
        if (modalBody) {
            const errorElements = modalBody.querySelectorAll(".modal-alert--error");
            errorElements.forEach(error => error.remove());
        }
    }

    closeModal() {
        // Guardar las selecciones actuales antes de cerrar
        if (this.tableComponent) {
            this.filterSelections[this.activeFilter] = new Set(this.tableComponent.selectedRows);
        }

        // Guardar el filtro activo actual antes de cerrar
        this.lastActiveFilter = this.activeFilter;

        this.modal.classList.remove("is-open");
        this.currentData = null;
        // NO resetear activeFilter aquí, se mantiene para la próxima apertura
        // this.activeFilter = "all";

        // Limpiar componente de tabla
        if (this.tableComponent) {
            this.tableComponent.clearSelection();
            this.tableComponent.rowsData = [];
            this.tableComponent.selectedRows = new Set();
        }

        // NO limpiar las selecciones guardadas por filtro - se mantienen para la próxima vez que se abra el modal
        // Si quieres limpiarlas al cerrar, descomenta las siguientes líneas:
        // this.filterSelections = {
        //     all: new Set(),
        //     to_update: new Set(),
        //     ok: new Set(),
        //     not_found: new Set(),
        // };

        // Resetear checkboxes
        const selectAllCheckbox = document.getElementById("select-all-checkbox");
        const selectAllAssignments = document.getElementById("select-all-assignments");
        if (selectAllCheckbox) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
        }
        if (selectAllAssignments) {
            selectAllAssignments.checked = false;
            selectAllAssignments.indeterminate = false;
        }

        // Cerrar menú contextual si está abierto
        const contextMenu = document.getElementById("assignment-context-menu");
        if (contextMenu) {
            contextMenu.style.display = "none";
        }

        this.hideAllSections();
    }
}

// Inicializar cuando el DOM esté listo
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
        window.zoomAssignmentManager = new ZoomAssignmentManager();
    });
} else {
    window.zoomAssignmentManager = new ZoomAssignmentManager();
}

export { ZoomAssignmentManager };
