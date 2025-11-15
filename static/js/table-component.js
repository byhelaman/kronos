/**
 * Componente de tabla reutilizable y configurable
 * Maneja selección, filtros, menú contextual, y renderizado de filas
 */

export class TableComponent {
    constructor(config) {
        this.config = {
            // Selectores DOM
            tableSelector: config.tableSelector,
            tbodySelector: config.tbodySelector,
            selectAllCheckboxSelector: config.selectAllCheckboxSelector,
            contextMenuSelector: config.contextMenuSelector,
            copyRowActionSelector: config.copyRowActionSelector,
            selectedCountSelector: config.selectedCountSelector,
            itemsCountSelector: config.itemsCountSelector,

            // Configuración de columnas
            columns: config.columns || [],

            // Callbacks
            onRowClick: config.onRowClick,
            onSelectionChange: config.onSelectionChange,
            onFilterChange: config.onFilterChange,
            onContextMenu: config.onContextMenu,
            onCopyRows: config.onCopyRows,

            // Configuración de renderizado
            rowRenderer: config.rowRenderer, // Función que renderiza una fila
            rowKeyExtractor: config.rowKeyExtractor, // Función que extrae una clave única de una fila
            rowClassExtractor: config.rowClassExtractor, // Función que extrae clases CSS de una fila

            // Configuración de selección
            canSelectRow: config.canSelectRow || (() => true), // Función que determina si una fila puede ser seleccionada
            getRowCheckbox: config.getRowCheckbox || ((row) => row.querySelector('input[type="checkbox"]')),

            // Configuración de filtros
            filterFunction: config.filterFunction || (() => true), // Función que filtra filas

            // Configuración de ordenamiento
            sortable: config.sortable !== false,
            sortFunction: config.sortFunction,

            // Mensajes
            noDataMessage: config.noDataMessage || "No data available",
            rowClass: config.rowClass || "table-row",
            selectedRowClass: config.selectedRowClass || "selected-row",
        };

        // Estado interno
        this.rowsData = [];
        this.selectedRows = new Set();
        this.lastClickedRowIndex = -1;
        this.sortCriteria = config.sortCriteria || [];

        // Referencias DOM
        this.table = null;
        this.tbody = null;
        this.selectAllCheckbox = null;
        this.contextMenu = null;
        this.copyRowAction = null;
        this.selectedCountEl = null;
        this.itemsCountEl = null;

        // Handlers
        this.rowClickHandler = null;
        this.rowMouseDownHandler = null;

        this.init();
    }

    init() {
        // Obtener referencias DOM
        this.table = document.querySelector(this.config.tableSelector);
        if (!this.table) {
            console.warn(`Table not found: ${this.config.tableSelector}`);
            return;
        }

        this.tbody = this.config.tbodySelector
            ? document.querySelector(this.config.tbodySelector)
            : this.table.tBodies[0];

        if (!this.tbody) {
            console.warn("Table body not found");
            return;
        }

        if (this.config.selectAllCheckboxSelector) {
            this.selectAllCheckbox = document.querySelector(this.config.selectAllCheckboxSelector);
        }

        if (this.config.contextMenuSelector) {
            this.contextMenu = document.querySelector(this.config.contextMenuSelector);
        }

        if (this.config.copyRowActionSelector) {
            this.copyRowAction = document.querySelector(this.config.copyRowActionSelector);
        }

        if (this.config.selectedCountSelector) {
            this.selectedCountEl = document.querySelector(this.config.selectedCountSelector);
        }

        if (this.config.itemsCountSelector) {
            this.itemsCountEl = document.querySelector(this.config.itemsCountSelector);
        }

        // Inicializar datos desde el DOM existente
        this.initializeFromDOM();

        // Bind eventos
        this.bindEvents();
    }

    initializeFromDOM() {
        const rows = Array.from(this.tbody.querySelectorAll('tr'));
        this.rowsData = rows.map((row, index) => {
            const checkbox = this.config.getRowCheckbox(row);
            const data = this.extractRowData(row);
            const key = this.config.rowKeyExtractor ? this.config.rowKeyExtractor(data, row) : index;

            return {
                row,
                data,
                key,
                visible: true,
                selected: checkbox?.checked || false,
                originalIndex: index,
            };
        });

        // Actualizar selección inicial
        this.rowsData.forEach(item => {
            if (item.selected) {
                this.selectedRows.add(item.key);
            }
        });
    }

    extractRowData(row) {
        const cells = Array.from(row.querySelectorAll('td'));
        const data = {};

        if (this.config.columns && this.config.columns.length > 0) {
            this.config.columns.forEach((col, index) => {
                if (cells[index]) {
                    data[col.key || col.label] = cells[index].textContent.trim();
                }
            });
        } else {
            // Si no hay configuración de columnas, extraer todos los datos
            cells.forEach((cell, index) => {
                data[`col_${index}`] = cell.textContent.trim();
            });
        }

        return data;
    }

    bindEvents() {
        // Checkbox "seleccionar todo"
        if (this.selectAllCheckbox) {
            this.selectAllCheckbox.addEventListener('change', (e) => {
                this.toggleSelectAll(e.target.checked);
            });
        }

        // Click en filas
        this.attachRowClickHandlers();

        // Menú contextual
        if (this.contextMenu) {
            this.initContextMenu();
        }
    }

    attachRowClickHandlers() {
        if (!this.tbody) return;

        // Remover listeners anteriores si existen
        if (this.rowClickHandler) {
            this.tbody.removeEventListener('click', this.rowClickHandler);
        }
        if (this.rowMouseDownHandler) {
            this.tbody.removeEventListener('mousedown', this.rowMouseDownHandler);
        }

        // Prevenir selección de texto en Shift+clic
        this.rowMouseDownHandler = (e) => {
            if (e.shiftKey) {
                const tr = e.target.closest(`.${this.config.rowClass}`);
                if (tr && this.config.getRowCheckbox(tr)) {
                    e.preventDefault();
                }
            }
        };

        this.rowClickHandler = (e) => {
            const tr = e.target.closest(`.${this.config.rowClass}`);
            if (!tr) return;

            const rowIndex = this.rowsData.findIndex(item => item.row === tr);
            if (rowIndex === -1) return;

            const rowData = this.rowsData[rowIndex];
            const checkbox = this.config.getRowCheckbox(tr);

            if (!checkbox) return;

            // Si se hizo clic directamente en el checkbox, ya se maneja en su propio listener
            if (e.target === checkbox || e.target.closest('input[type="checkbox"]')) {
                return;
            }

            // Manejar clic en la fila
            this.handleRowClick(e, tr, rowIndex, rowData, checkbox);
        };

        this.tbody.addEventListener('mousedown', this.rowMouseDownHandler);
        this.tbody.addEventListener('click', this.rowClickHandler);

        // Listeners para checkboxes individuales
        this.rowsData.forEach(item => {
            const checkbox = this.config.getRowCheckbox(item.row);
            if (checkbox) {
                checkbox.addEventListener('change', (e) => {
                    this.toggleRowSelection(item, e.target.checked);
                    const rowIndex = this.rowsData.findIndex(r => r === item);
                    if (rowIndex !== -1) {
                        this.lastClickedRowIndex = rowIndex;
                    }
                    this.updateSelectionUI();
                });
            }
        });
    }

    handleRowClick(e, tr, currentRowIndex, rowData, checkbox) {
        // Determinar el nuevo estado de selección
        let newSelectionState = !checkbox.checked;

        // Lógica de Shift+clic
        if (
            e.shiftKey &&
            this.lastClickedRowIndex > -1 &&
            this.lastClickedRowIndex !== currentRowIndex
        ) {
            e.preventDefault();
            e.stopPropagation();

            const start = Math.min(this.lastClickedRowIndex, currentRowIndex);
            const end = Math.max(this.lastClickedRowIndex, currentRowIndex);

            // Aplicar el estado de selección a todo el rango (solo filas visibles y seleccionables)
            for (let i = start; i <= end; i++) {
                const rowItem = this.rowsData[i];
                if (!rowItem || !rowItem.visible) continue;

                if (this.config.canSelectRow(rowItem.data, rowItem.row)) {
                    const rowCheckbox = this.config.getRowCheckbox(rowItem.row);
                    if (rowCheckbox) {
                        rowCheckbox.checked = newSelectionState;
                        this.toggleRowSelection(rowItem, newSelectionState);
                    }
                }
            }
        } else {
            // Lógica de clic normal
            checkbox.checked = newSelectionState;
            this.toggleRowSelection(rowData, newSelectionState);
        }

        // Actualizar el último índice clickeado
        this.lastClickedRowIndex = currentRowIndex;

        // Callback personalizado
        if (this.config.onRowClick) {
            this.config.onRowClick(rowData, e);
        }

        // Actualizar UI
        this.updateSelectionUI();
    }

    toggleRowSelection(rowData, isSelected) {
        rowData.selected = isSelected;

        if (isSelected) {
            this.selectedRows.add(rowData.key);
        } else {
            this.selectedRows.delete(rowData.key);
        }

        // Actualizar clases CSS
        if (isSelected) {
            rowData.row.classList.add(this.config.selectedRowClass);
        } else {
            rowData.row.classList.remove(this.config.selectedRowClass);
        }

        // Callback
        if (this.config.onSelectionChange) {
            this.config.onSelectionChange(this.getSelectedRows(), this.selectedRows.size);
        }
    }

    toggleSelectAll(checked) {
        const visibleRows = this.rowsData.filter(item => item.visible);

        visibleRows.forEach(item => {
            if (this.config.canSelectRow(item.data, item.row)) {
                const checkbox = this.config.getRowCheckbox(item.row);
                if (checkbox) {
                    checkbox.checked = checked;
                    this.toggleRowSelection(item, checked);
                }
            }
        });

        this.updateSelectionUI();
    }

    updateSelectionUI() {
        // Actualizar contador de seleccionados
        if (this.selectedCountEl) {
            this.selectedCountEl.textContent = this.selectedRows.size;
        }

        // Actualizar texto del botón "Copy row" / "Copy rows" en el menú contextual
        if (this.copyRowAction) {
            const selectedCount = this.selectedRows.size;
            const span = this.copyRowAction.querySelector('span');
            if (span) {
                span.textContent = selectedCount > 1 ? "Copy rows" : "Copy row";
            } else {
                this.copyRowAction.textContent = selectedCount > 1 ? "Copy rows" : "Copy row";
            }
        }

        // Actualizar checkbox "seleccionar todo"
        if (this.selectAllCheckbox) {
            const visibleRows = this.rowsData.filter(item => item.visible);
            const selectableRows = visibleRows.filter(item =>
                this.config.canSelectRow(item.data, item.row)
            );
            const selectedVisible = selectableRows.filter(item => item.selected);

            if (selectedVisible.length === 0) {
                this.selectAllCheckbox.checked = false;
                this.selectAllCheckbox.indeterminate = false;
            } else if (selectedVisible.length === selectableRows.length) {
                this.selectAllCheckbox.checked = true;
                this.selectAllCheckbox.indeterminate = false;
            } else {
                this.selectAllCheckbox.checked = false;
                this.selectAllCheckbox.indeterminate = true;
            }
        }
    }

    initContextMenu() {
        if (!this.contextMenu || !this.tbody) return;

        // Click derecho en filas
        this.tbody.addEventListener('contextmenu', (e) => {
            e.preventDefault();

            const tr = e.target.closest(`.${this.config.rowClass}`);
            if (!tr) return;

            const rowIndex = this.rowsData.findIndex(item => item.row === tr);
            if (rowIndex === -1) return;

            const rowData = this.rowsData[rowIndex];

            // Si la fila clickeada NO está seleccionada, deselecciona todo y selecciona solo esta fila
            if (!rowData.selected) {
                this.toggleSelectAll(false);
                const checkbox = this.config.getRowCheckbox(tr);
                if (checkbox) {
                    checkbox.checked = true;
                    this.toggleRowSelection(rowData, true);
                    this.updateSelectionUI();
                }
            }

            // Actualizar texto del botón "Copy row" / "Copy rows" antes de mostrar el menú
            if (this.copyRowAction) {
                const selectedCount = this.selectedRows.size;
                const span = this.copyRowAction.querySelector('span');
                if (span) {
                    span.textContent = selectedCount > 1 ? "Copy rows" : "Copy row";
                } else {
                    this.copyRowAction.textContent = selectedCount > 1 ? "Copy rows" : "Copy row";
                }
            }

            // Callback personalizado - puede cancelar el menú
            let shouldShowMenu = true;
            if (this.config.onContextMenu) {
                const result = this.config.onContextMenu(rowData, e);
                // Si el callback retorna false, no mostrar el menú
                if (result === false) {
                    shouldShowMenu = false;
                }
            }

            // Mostrar menú contextual solo si no fue cancelado
            if (!shouldShowMenu) {
                return;
            }

            const x = e.clientX;
            const y = e.clientY;

            this.contextMenu.style.position = "fixed";
            this.contextMenu.style.top = `${y}px`;
            this.contextMenu.style.left = `${x}px`;
            this.contextMenu.style.display = "block";

            // Ajustar si el menú se sale de la pantalla
            setTimeout(() => {
                const rect = this.contextMenu.getBoundingClientRect();
                const viewportWidth = window.innerWidth;
                const viewportHeight = window.innerHeight;

                if (rect.right > viewportWidth) {
                    this.contextMenu.style.left = `${viewportWidth - rect.width - 10}px`;
                }
                if (rect.bottom > viewportHeight) {
                    this.contextMenu.style.top = `${viewportHeight - rect.height - 10}px`;
                }
                if (rect.left < 0) {
                    this.contextMenu.style.left = "10px";
                }
                if (rect.top < 0) {
                    this.contextMenu.style.top = "10px";
                }
            }, 0);
        });

        // Cerrar menú al hacer clic fuera
        const closeContextMenu = (e) => {
            if (this.contextMenu && this.contextMenu.style.display === "block") {
                if (!this.contextMenu.contains(e.target)) {
                    this.contextMenu.style.display = "none";
                }
            }
        };
        document.addEventListener('click', closeContextMenu, true);

        // Cerrar con ESC
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.contextMenu && this.contextMenu.style.display === "block") {
                this.contextMenu.style.display = "none";
            }
        });
    }

    // Métodos públicos para manipular datos

    setData(data, render = true) {
        this.rowsData = data.map((item, index) => {
            const key = this.config.rowKeyExtractor ? this.config.rowKeyExtractor(item, null) : index;
            return {
                data: item,
                key,
                visible: true,
                selected: false,
                originalIndex: index,
            };
        });

        if (render) {
            this.render();
        }
    }

    addRow(rowData, render = true) {
        const key = this.config.rowKeyExtractor ? this.config.rowKeyExtractor(rowData, null) : this.rowsData.length;
        const newRow = {
            data: rowData,
            key,
            visible: true,
            selected: false,
            originalIndex: this.rowsData.length,
        };

        this.rowsData.push(newRow);

        if (render) {
            this.render();
        }

        return newRow;
    }

    removeRow(key, render = true) {
        const index = this.rowsData.findIndex(item => item.key === key);
        if (index !== -1) {
            this.selectedRows.delete(key);
            this.rowsData.splice(index, 1);

            if (render) {
                this.render();
            }
            return true;
        }
        return false;
    }

    render() {
        if (!this.tbody) return;

        // Aplicar filtros
        this.applyFilters();

        // Aplicar ordenamiento
        if (this.config.sortable && this.sortCriteria.length > 0) {
            this.sortData();
        }

        // Renderizar filas
        const frag = document.createDocumentFragment();
        let visibleCount = 0;

        this.rowsData.forEach((item) => {
            // Mostrar/ocultar fila
            item.row.style.display = item.visible ? "" : "none";

            // Aplicar clases CSS personalizadas
            if (this.config.rowClassExtractor) {
                const classes = this.config.rowClassExtractor(item.data, item.row);
                if (classes) {
                    item.row.className = `${this.config.rowClass} ${classes}`;
                } else {
                    item.row.className = this.config.rowClass;
                }
            }

            // Aplicar clase de selección
            if (item.selected) {
                item.row.classList.add(this.config.selectedRowClass);
            } else {
                item.row.classList.remove(this.config.selectedRowClass);
            }

            frag.appendChild(item.row);
            if (item.visible) visibleCount++;
        });

        this.tbody.innerHTML = "";
        this.tbody.appendChild(frag);

        // Mostrar mensaje "sin datos" si es necesario
        this.updateNoDataMessage(visibleCount);

        // Actualizar contadores
        if (this.itemsCountEl) {
            this.itemsCountEl.textContent = visibleCount;
        }

        this.updateSelectionUI();

        // Re-attach handlers después de renderizar
        this.attachRowClickHandlers();
    }

    applyFilters() {
        if (!this.config.filterFunction) {
            this.rowsData.forEach(item => item.visible = true);
            return;
        }

        this.rowsData.forEach(item => {
            item.visible = this.config.filterFunction(item.data, item.row);
        });
    }

    sortData() {
        if (this.sortCriteria.length === 0 || !this.config.sortFunction) return;

        // Ordenar los datos usando la función de ordenamiento configurada
        this.rowsData.sort((a, b) => {
            for (const criterion of this.sortCriteria) {
                const comparison = this.config.sortFunction(a.data, b.data, criterion);
                if (comparison !== 0) {
                    return criterion.direction === "asc" ? comparison : -comparison;
                }
            }
            return 0;
        });
    }

    // Método público para actualizar criterios de ordenamiento
    setSortCriteria(criteria) {
        this.sortCriteria = criteria;
        this.render();
    }

    updateNoDataMessage(visibleCount) {
        const existingNoData = this.tbody.querySelector('#noDataRow');

        if (visibleCount === 0 && !existingNoData) {
            const tr = document.createElement('tr');
            tr.id = 'noDataRow';
            const td = document.createElement('td');
            td.colSpan = this.table.querySelectorAll('thead th').length;
            td.textContent = this.config.noDataMessage;
            td.style.textAlign = "center";
            td.style.padding = "0.75rem 1rem";
            tr.appendChild(td);
            this.tbody.appendChild(tr);
        } else if (visibleCount > 0 && existingNoData) {
            existingNoData.remove();
        }
    }

    // Métodos públicos para obtener datos

    getSelectedRows() {
        return this.rowsData.filter(item => item.selected).map(item => item.data);
    }

    getSelectedKeys() {
        return Array.from(this.selectedRows);
    }

    getVisibleRows() {
        return this.rowsData.filter(item => item.visible).map(item => item.data);
    }

    getAllRows() {
        return this.rowsData.map(item => item.data);
    }

    getRowCount() {
        return this.rowsData.length;
    }

    getVisibleRowCount() {
        return this.rowsData.filter(item => item.visible).length;
    }

    getSelectedRowCount() {
        return this.selectedRows.size;
    }

    // Métodos para copiar filas

    copySelectedRows() {
        const selectedRows = this.getSelectedRows();

        if (selectedRows.length === 0) {
            return false;
        }

        if (this.config.onCopyRows) {
            return this.config.onCopyRows(selectedRows);
        }

        return false;
    }

    // Métodos para limpiar

    clearSelection() {
        this.toggleSelectAll(false);
    }

    destroy() {
        if (this.rowClickHandler && this.tbody) {
            this.tbody.removeEventListener('click', this.rowClickHandler);
        }
        if (this.rowMouseDownHandler && this.tbody) {
            this.tbody.removeEventListener('mousedown', this.rowMouseDownHandler);
        }

        this.rowsData = [];
        this.selectedRows.clear();
    }
}

