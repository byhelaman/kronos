import * as utils from "./utils.js";
import { notificationManager } from "./notification.js";
import { TableComponent } from "./table-component.js";

const manager = (function () {
  let tableComponent;
  let filterInstructor, filterGroup, filterOverlaps;
  let clearFiltersBtn, deleteBtn, downloadBtn, copyScheduleAction;
  let copyInstructorsAction, overlapCountEl, deleteForm, selectedRowsDeleteInput;
  let restoreForm, deleteDataForm, restoreBtn, csrfToken;
  let copyRowAction, deselectAllAction;
  let btnAutoAssign;

  let columnsConfig = [];
  let sortCriteria = [];

  function sortData() {
    if (sortCriteria.length === 0 || !tableComponent) return;

    // Actualizar criterios de ordenamiento en el componente
    tableComponent.setSortCriteria(sortCriteria);
  }

  function updateSortHeaders() {
    columnsConfig.forEach((c) => {
      if (c.sortable) c.headerEl.textContent = c.headerEl.dataset.originalText;
    });

    sortCriteria.forEach((sc) => {
      const sortedCfg = columnsConfig.find((c) => c.label === sc.label);
      if (sortedCfg) {
        const arrow = sc.direction === "asc" ? " ↑" : " ↓";
        sortedCfg.headerEl.textContent =
          sortedCfg.headerEl.dataset.originalText + arrow;
      }
    });
  }

  function _calculateAllOverlaps() {
    if (!tableComponent) return;

    const rowsData = tableComponent.rowsData;
    rowsData.forEach((item) => (item.data.overlapped = false));

    const activeRows = rowsData.filter((it) => it.data.status === "active");

    const byInstructor = {};
    activeRows.forEach((it) => {
      const key = it.data["Instructor"] || "__NO_INSTRUCTOR__";
      (byInstructor[key] = byInstructor[key] || []).push(it);
    });

    Object.values(byInstructor).forEach((list) => {
      for (let i = 0; i < list.length; i++) {
        for (let j = i + 1; j < list.length; j++) {
          const a = list[i],
            b = list[j];
          if (
            utils.parseTimeToMinutes(a.data["Start Time"]) <
            utils.parseTimeToMinutes(b.data["End Time"]) &&
            utils.parseTimeToMinutes(b.data["Start Time"]) <
            utils.parseTimeToMinutes(a.data["End Time"])
          ) {
            a.data.overlapped = b.data.overlapped = true;
          }
        }
      }
    });

    const byGroupAndTime = {};
    activeRows.forEach((it) => {
      const key = `${it.data["Group"]}_${it.data["Start Time"]}_${it.data["End Time"]}`;
      (byGroupAndTime[key] = byGroupAndTime[key] || []).push(it);
    });

    Object.values(byGroupAndTime).forEach((list) => {
      if (list.length > 1) {
        const instructorsInSlot = new Set(
          list.map((item) => item.data["Instructor"])
        );
        if (instructorsInSlot.size > 1) {
          list.forEach((item) => (item.data.overlapped = true));
        }
      }
    });
  }

  function onFilterChange() {
    const instructorFilters = filterInstructor.value
      .toLowerCase()
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    const groupFilters = filterGroup.value
      .toLowerCase()
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    const onlyOverlap = filterOverlaps.checked;

    // Actualizar función de filtro del componente
    tableComponent.config.filterFunction = (data, row) => {
      const instructorData = data["Instructor"]?.toLowerCase() || "";
      const groupData = data["Group"]?.toLowerCase() || "";

      const passInst =
        instructorFilters.length === 0 ||
        instructorFilters.some((filter) => instructorData.includes(filter));
      const passGrp =
        groupFilters.length === 0 ||
        groupFilters.some((filter) => groupData.includes(filter));
      const passOverlap = !onlyOverlap || data.overlapped;
      const passStatus = data.status === "active";

      return passInst && passGrp && passOverlap && passStatus;
    };

    _calculateAllOverlaps();
    tableComponent.render();
    updateOverlapCount();
  }

  function updateOverlapCount() {
    if (overlapCountEl) {
      const visibleRows = tableComponent.rowsData.filter(
        (it) => it.visible && it.data.overlapped
      );
      overlapCountEl.textContent = visibleRows.length;
    }
  }

  function updateAutoAssignButton() {
    if (!btnAutoAssign || !tableComponent) return;

    // Verificar si hay filas activas (no eliminadas)
    const hasActiveRows = tableComponent.rowsData.some(
      (item) => item.data.status === "active"
    );

    btnAutoAssign.disabled = !hasActiveRows;
  }

  function handleSortClick(e, cfg) {
    const existingIndex = sortCriteria.findIndex(
      (sc) => sc.label === cfg.label
    );
    const isExisting = existingIndex > -1;

    // Ctrl/Cmd + Click: Remover filtro de criterios múltiples
    if (e.ctrlKey || e.metaKey) {
      if (isExisting) {
        sortCriteria.splice(existingIndex, 1);
      }
    }
    // Shift + Click: Añadir a criterios múltiples (o cambiar dirección si ya existe)
    else if (e.shiftKey) {
      if (isExisting) {
        sortCriteria[existingIndex].direction =
          sortCriteria[existingIndex].direction === "asc" ? "desc" : "asc";
      } else {
        sortCriteria.push({ label: cfg.label, direction: "asc" });
      }
    }
    // Click simple: Ciclo entre asc → desc → desactivar
    else {
      if (isExisting && sortCriteria.length === 1) {
        // Si ya está ordenada y es la única, ciclo: asc → desc → desactivar
        if (sortCriteria[0].direction === "asc") {
          sortCriteria[0].direction = "desc";
        } else {
          // Desactivar: remover el criterio
          sortCriteria = [];
        }
      } else if (isExisting && sortCriteria.length > 1) {
        // Si hay múltiples criterios, cambiar solo esta columna a la siguiente dirección o remover
        if (sortCriteria[existingIndex].direction === "asc") {
          sortCriteria[existingIndex].direction = "desc";
        } else {
          // Remover este criterio específico
          sortCriteria.splice(existingIndex, 1);
        }
      } else {
        // Si no está ordenada, empezar con asc
        sortCriteria = [{ label: cfg.label, direction: "asc" }];
      }
    }

    sortData();
    updateSortHeaders();
    tableComponent.render();
  }

  function copySelectedRowsToClipboard() {
    const selectedRows = tableComponent.getSelectedRows();
    if (selectedRows.length === 0) {
      notificationManager.warning("No rows selected to copy.");
      return;
    }

    try {
      const textToCopy = selectedRows
        .map((item) => {
          const date = item["Date"];
          const groupName = item["Group"];
          const startTime24h = utils.convertTo24HourFormat(item["Start Time"]);
          const endTime24h = utils.convertTo24HourFormat(item["End Time"]);
          return `${date}\n${groupName}\n${startTime24h} - ${endTime24h}`;
        })
        .join("\n\n");

      navigator.clipboard
        .writeText(textToCopy)
        .then(() => {
          const s = selectedRows.length > 1 ? "s" : "";
          notificationManager.success(`Copied ${selectedRows.length} row${s}`);
        })
        .catch((err) => {
          console.error("Error copying selected rows: ", err);
          notificationManager.error("Error: Could not copy selected rows.");
        });
    } catch (err) {
      console.error("Error during copy formatting:", err);
      notificationManager.error("Error: Could not format data for copying.");
    }
  }

  async function handleFormSubmit(form, confirmMessage, successCallback) {
    if (confirmMessage && !confirm(confirmMessage)) {
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;

    try {
      const formData = new FormData(form);
      const response = await fetch(form.action, {
        method: form.method,
        body: formData,
        headers: { Accept: "application/json" },
      });

      if (!response.ok) {
        let errorMsg = `Server error: ${response.status} ${response.statusText}`;
        try {
          const errorResult = await response.json();
          errorMsg = errorResult.message || errorMsg;
        } catch (e) { }
        throw new Error(errorMsg);
      }

      const result = await response.json();

      if (result.new_csrf_token) {
        document
          .querySelectorAll('input[name="csrf_token"]')
          .forEach((input) => {
            input.value = result.new_csrf_token;
          });

        csrfToken = result.new_csrf_token;
      }
      successCallback(result);
    } catch (err) {
      console.error("Fetch error:", err);
      notificationManager.error(
        `An error occurred: ${err.message}. Please try again.`
      );

      if (submitBtn) {
        submitBtn.disabled = false;
      }
    }
  }

  function bindEvents() {
    filterInstructor.addEventListener(
      "input",
      utils.debounce(onFilterChange, 120)
    );
    filterGroup.addEventListener("input", utils.debounce(onFilterChange, 120));
    filterOverlaps.addEventListener("change", onFilterChange);

    clearFiltersBtn.addEventListener("click", () => {
      // Solo limpiar los filtros, no la selección
      filterInstructor.value = "";
      filterGroup.value = "";
      filterOverlaps.checked = false;
      setTimeout(() => {
        onFilterChange();
      }, 0);
    });

    deleteForm?.addEventListener("submit", (e) => {
      e.preventDefault();
      const selectedRows = tableComponent.getSelectedRows();
      const ids_to_delete = selectedRows.map((row) => row.id || row["ID"]);

      if (ids_to_delete.length === 0) return;

      selectedRowsDeleteInput.value = ids_to_delete.join(",");

      handleFormSubmit(deleteForm, null, (result) => {
        const deletedIds = new Set(ids_to_delete);
        tableComponent.rowsData.forEach((item) => {
          if (deletedIds.has(item.data.id || item.data["ID"])) {
            item.selected = false;
            tableComponent.selectedRows.delete(item.key);
            item.visible = false;
            item.data.status = "deleted";
          }
        });

        _calculateAllOverlaps();
        tableComponent.render();
        updateOverlapCount();
        updateAutoAssignButton();

        if (restoreBtn) restoreBtn.disabled = false;

        // Actualizar el modal de zoom-assignment si está abierto
        if (window.zoomAssignmentManager && window.zoomAssignmentManager.isModalOpen()) {
          window.zoomAssignmentManager.refreshModal();
        }

        if (result.message) {
          notificationManager.success(result.message);
        } else {
          const count = ids_to_delete.length;
          notificationManager.success(
            `Se ${count === 1 ? "eliminó" : "eliminaron"} ${count} fila${count === 1 ? "" : "s"}.`
          );
        }
      });
    });

    restoreForm?.addEventListener("submit", (e) => {
      e.preventDefault();
      const confirmMsg =
        "This will restore all previously deleted rows. Are you sure?";

      handleFormSubmit(restoreForm, confirmMsg, (result) => {
        tableComponent.rowsData.forEach((item) => {
          if (item.data.status === "deleted") {
            item.data.status = "active";
            item.selected = false;
            tableComponent.selectedRows.delete(item.key);
            // Desmarcar el checkbox en el DOM
            const checkbox = tableComponent.config.getRowCheckbox(item.row);
            if (checkbox) {
              checkbox.checked = false;
            }
          }
        });

        _calculateAllOverlaps();
        onFilterChange();

        // Actualizar UI de selección para asegurar que todo esté sincronizado
        tableComponent.updateSelectionUI();
        updateAutoAssignButton();

        // Actualizar el modal de zoom-assignment si está abierto
        if (window.zoomAssignmentManager && window.zoomAssignmentManager.isModalOpen()) {
          window.zoomAssignmentManager.refreshModal();
        }

        if (restoreBtn) {
          const hasDeletedRows = tableComponent.rowsData.some(
            (it) => it.data.status === "deleted"
          );
          restoreBtn.disabled = !hasDeletedRows;
        }

        notificationManager.success(result.message);
      });
    });

    deleteDataForm?.addEventListener("submit", (e) => {
      e.preventDefault();
      const confirmMsg =
        "Are you sure you want to delete all data permanently?";

      handleFormSubmit(deleteDataForm, confirmMsg, (result) => {
        tableComponent.rowsData = [];
        tableComponent.selectedRows.clear();
        tableComponent.render();
        updateAutoAssignButton();
        if (restoreBtn) restoreBtn.disabled = true;

        if (result.message) {
          notificationManager.success(result.message);
        } else {
          notificationManager.success(
            "Todos los datos han sido eliminados permanentemente."
          );
        }
      });
    });

    downloadBtn?.addEventListener("click", () => {
      window.location.href = "/download-excel";
    });

    // Caché para el endpoint /schedule
    let scheduleCache = null;
    let scheduleCacheTimestamp = 0;
    const SCHEDULE_CACHE_TTL = 30000;

    copyScheduleAction?.addEventListener("click", () => {
      const now = Date.now();

      if (
        scheduleCache &&
        now - scheduleCacheTimestamp < SCHEDULE_CACHE_TTL
      ) {
        navigator.clipboard
          .writeText(scheduleCache)
          .then(() => {
            notificationManager.success("Copied Schedule (from cache)");
          })
          .catch((err) => {
            console.error(err);
            notificationManager.error(
              "Error: No se pudo copiar al portapapeles."
            );
          });
        return;
      }

      fetch("/schedule", { method: "GET" })
        .then((res) => {
          if (!res.ok)
            throw new Error(
              "Error copying data. Endpoint /schedule no encontrado?"
            );
          return res.text();
        })
        .then((txt) => {
          scheduleCache = txt;
          scheduleCacheTimestamp = Date.now();

          navigator.clipboard.writeText(txt);
          notificationManager.success("Copied Schedule");
        })
        .catch((err) => {
          console.error(err);
          notificationManager.error(
            "Error: No se pudo copiar. Verifica el endpoint /schedule."
          );
        });
    });

    copyInstructorsAction?.addEventListener("click", () => {
      const instructorSet = new Set(
        tableComponent
          .getAllRows()
          .map((item) => item["Instructor"]?.trim())
          .filter(Boolean)
      );
      const uniqueInstructors = Array.from(instructorSet);
      const textToCopy = uniqueInstructors.join("\n");
      navigator.clipboard
        .writeText(textToCopy)
        .then(() => {
          notificationManager.success("Copied Instructors");
        })
        .catch((err) => {
          console.error(err);
          notificationManager.error("Error: Could not copy instructors.");
        });
    });

    // Menú contextual
    const contextMenu = document.getElementById("row-context-menu");
    if (contextMenu) {
      copyRowAction = document.getElementById("copy-row-action");
      deselectAllAction = document.getElementById("deselect-all-action");

      copyRowAction?.addEventListener("click", () => {
        copySelectedRowsToClipboard();
        contextMenu.style.display = "none";
      });

      deselectAllAction?.addEventListener("click", () => {
        tableComponent.clearSelection();
        contextMenu.style.display = "none";
      });
    }

    // Ordenamiento
    columnsConfig.forEach((cfg) => {
      if (cfg.sortable) {
        cfg.headerEl.style.cursor = "pointer";
        cfg.headerEl.addEventListener("click", (e) => handleSortClick(e, cfg));
      }
    });
  }

  function init(tableSelector) {
    const table = document.querySelector(tableSelector);
    if (!table) return;

    const tbody = table.tBodies[0];
    const headers = Array.from(table.tHead.querySelectorAll("th"));

    // Configurar columnas
    headers.forEach((th) => {
      th.dataset.originalText = th.textContent.trim();
    });

    columnsConfig = headers.map((th, idx) => {
      // Verificar si tiene atributo data-sortable definido
      // Por defecto, todas excepto la primera son ordenables (idx > 0)
      let sortable = idx > 0;
      if (th.hasAttribute("data-sortable")) {
        const sortableAttr = th.getAttribute("data-sortable");
        // Si es "false", deshabilitar ordenamiento
        // Si es "true" o vacío (solo data-sortable), habilitar ordenamiento
        sortable = sortableAttr !== "false";
      }
      
      return {
        label: th.dataset.originalText,
        index: idx,
        parser: /time/i.test(th.dataset.originalText)
          ? utils.parseTimeToMinutes
          : utils.textParser,
        sortable: sortable,
        headerEl: th,
      };
    });

    // Función de ordenamiento personalizada
    const sortFunction = (a, b, criterion) => {
      const cfg = columnsConfig.find((c) => c.label === criterion.label);
      if (!cfg) return 0;

      const va = cfg.parser(a[criterion.label] || "");
      const vb = cfg.parser(b[criterion.label] || "");
      return va < vb ? -1 : va > vb ? 1 : 0;
    };

    // Función para extraer clave única de una fila
    const rowKeyExtractor = (data, row) => {
      return row?.dataset?.id || data.id || data["ID"] || `${data["Date"]}_${data["Group"]}_${data["Start Time"]}`;
    };

    // Función para extraer clases CSS de una fila
    const rowClassExtractor = (data, row) => {
      const units = parseInt(data["Units"], 10) || 0;
      const showWarning = data.overlapped && units <= 0;
      return showWarning ? "row--warning" : "";
    };

    // Función para copiar filas
    const onCopyRows = (selectedRows) => {
      copySelectedRowsToClipboard();
      return true;
    };

    // Crear componente de tabla
    tableComponent = new TableComponent({
      tableSelector: tableSelector,
      selectAllCheckboxSelector: "#select-all",
      contextMenuSelector: "#row-context-menu",
      copyRowActionSelector: "#copy-row-action",
      selectedCountSelector: "#stat-selected",
      itemsCountSelector: "#stat-items",
      columns: columnsConfig,
      rowClass: "data-table-row",
      selectedRowClass: "selected-row",
      rowKeyExtractor,
      rowClassExtractor,
      getRowCheckbox: (row) => row.querySelector(".row-select"),
      onCopyRows,
      sortFunction,
      noDataMessage: "Not found data",
      onSelectionChange: (selectedRows, selectedCount) => {
        // Habilitar/deshabilitar el botón de eliminar según las filas seleccionadas
        if (deleteBtn) {
          deleteBtn.disabled = selectedCount === 0;
        }
      },
    });

    // Inicializar datos desde el DOM
    const rows = Array.from(tbody.querySelectorAll("tr"));
    const rowsData = rows.map((row, i) => {
      if (row.cells.length < columnsConfig.length) return null;

      const data = {};
      columnsConfig.forEach((cfg) => {
        data[cfg.label] = row.cells[cfg.index]?.textContent.trim() || "";
      });

      // Convertir tiempos a formato 24h
      const startTimeCfg = columnsConfig.find((c) => c.label === "Start Time");
      const endTimeCfg = columnsConfig.find((c) => c.label === "End Time");
      const simpleTimeCfg = columnsConfig.find((c) => c.label === "Time");

      if (startTimeCfg) {
        const cell = row.cells[startTimeCfg.index];
        if (cell) {
          const originalTime = data[startTimeCfg.label];
          cell.textContent = utils.convertTo24HourFormat(originalTime);
        }
      }

      if (endTimeCfg) {
        const cell = row.cells[endTimeCfg.index];
        if (cell) {
          const originalTime = data[endTimeCfg.label];
          cell.textContent = utils.convertTo24HourFormat(originalTime);
        }
      }

      if (simpleTimeCfg) {
        const cell = row.cells[simpleTimeCfg.index];
        if (cell) {
          const originalStartTime = data["Start Time"];
          const originalEndTime = data["End Time"];
          if (originalStartTime && originalEndTime) {
            const startTime24h = utils.convertTo24HourFormat(originalStartTime);
            const endTime24h = utils.convertTo24HourFormat(originalEndTime);
            cell.textContent = `${startTime24h} - ${endTime24h}`;
          }
        }
      }

      const cb = row.querySelector(".row-select");
      row.dataset.originalIndex = i;

      return {
        data: {
          ...data,
          id: row.dataset.id,
          status: "active",
          overlapped: false,
        },
        row,
        key: rowKeyExtractor({ ...data, id: row.dataset.id }, row),
        visible: true,
        selected: !!cb?.checked,
        originalIndex: i,
      };
    }).filter(Boolean);

    // Aplicar orden inicial por defecto: Area (asc)
    const defaultSortCriteria = [];
    const areaColumn = columnsConfig.find((c) => c.label === "Area");
    
    if (areaColumn && areaColumn.sortable) {
      defaultSortCriteria.push({ label: "Area", direction: "asc" });
    }
    
    tableComponent.rowsData = rowsData;
    
    // Si hay columnas de ordenamiento por defecto, aplicarlas
    if (defaultSortCriteria.length > 0) {
      sortCriteria = defaultSortCriteria;
      tableComponent.setSortCriteria(defaultSortCriteria);
      updateSortHeaders();
    }
    
    tableComponent.selectedRows = new Set(
      rowsData.filter((item) => item.selected).map((item) => item.key)
    );

    // Obtener referencias a elementos del DOM
    filterInstructor = document.getElementById("filter-instructor");
    filterGroup = document.getElementById("filter-group");
    filterOverlaps = document.getElementById("filter-overlaps");
    clearFiltersBtn = document.querySelector('#filter-form button[type="reset"]');
    deleteForm = document.getElementById("selection-form");
    restoreForm = document.getElementById("restore-form");
    deleteDataForm = document.getElementById("delete-data-form");

    if (restoreForm) {
      restoreBtn = restoreForm.querySelector('button[type="submit"]');
    }

    if (deleteForm) {
      deleteBtn = deleteForm.querySelector('button[type="submit"]');
      selectedRowsDeleteInput = document.getElementById("selected_ids");
      csrfToken = deleteForm.querySelector('input[name="csrf_token"]').value;
    }

    downloadBtn = document.querySelector(
      'button[aria-label="Download as Excel"]'
    );
    copyScheduleAction = document.getElementById("copy-schedule-action");
    copyInstructorsAction = document.getElementById("copy-instructors-action");
    overlapCountEl = document.getElementById("stat-overlaps");
    btnAutoAssign = document.getElementById("btn-auto-assign");

    // Calcular overlaps y renderizar
    _calculateAllOverlaps();
    bindEvents();
    onFilterChange();

    // Actualizar estado inicial del botón de eliminar
    if (deleteBtn) {
      deleteBtn.disabled = tableComponent.selectedRows.size === 0;
    }

    // Actualizar estado inicial del botón de auto-assign
    updateAutoAssignButton();
  }

  return { init: init };
})();

export const TableManager = manager;
