import * as utils from "./utils.js";

const manager = (function () {
  let table,
    tbody,
    headers,
    contextMenu,
    copyRowAction,
    deselectAllAction,
    filterInstructor,
    filterGroup,
    filterOverlaps;
  let clearFiltersBtn,
    selectAllCheckbox,
    deleteBtn,
    downloadBtn,
    copySelectedAction,
    copyScheduleAction;
  let copyInstructorsAction,
    selectedCountEl,
    itemsCountEl,
    overlapCountEl,
    deleteForm,
    selectedRowsDeleteInput;
  let restoreForm, deleteDataForm, restoreBtn, csrfToken;

  let columnsConfig = [];
  let rowsData = [];
  let sortCriteria = [];
  let rightClickedRow = null;

  function sortData() {
    if (sortCriteria.length === 0) return;

    rowsData.sort((a, b) => {
      for (const criterion of sortCriteria) {
        const cfg = columnsConfig.find((c) => c.label === criterion.label);
        if (!cfg) continue;

        const va = cfg.parser(a.data[criterion.label]);
        const vb = cfg.parser(b.data[criterion.label]);
        let comparison = va < vb ? -1 : va > vb ? 1 : 0;

        if (comparison !== 0) {
          return criterion.direction === "asc" ? comparison : -comparison;
        }
      }
      return 0;
    });
  }

  function render() {
    const frag = document.createDocumentFragment();
    let visibleCount = 0;

    rowsData.forEach((item) => {
      item.row.style.display = item.visible ? "" : "none";

      const units = parseInt(item.data["Units"], 10) || 0;
      const showWarning = item.overlapped && units <= 0;
      item.row.classList.toggle("row--warning", showWarning);

      frag.appendChild(item.row);
      if (item.visible) visibleCount++;
    });

    tbody.innerHTML = "";
    tbody.appendChild(frag);

    if (itemsCountEl) {
      itemsCountEl.textContent = visibleCount;
    }

    const selCount = rowsData.filter((it) => it.selected).length;
    if (selectedCountEl) {
      selectedCountEl.textContent = selCount;
    }

    if (overlapCountEl) {
      overlapCountEl.textContent = rowsData.filter(
        (it) => it.visible && it.overlapped
      ).length;
    }

    const existingNoData = document.getElementById("noDataRow");
    if (visibleCount === 0 && !existingNoData) {
      const tr = document.createElement("tr");
      tr.id = "noDataRow";
      const td = document.createElement("td");
      td.colSpan = headers.length;
      td.textContent = "Not found data";
      td.style.textAlign = "center";
      tr.appendChild(td);
      tbody.appendChild(tr);
    } else if (visibleCount > 0 && existingNoData) {
      existingNoData.remove();
    }
  }

  function updateSelectedCount() {
    const totalSelectedCount = rowsData.filter((it) => it.selected).length;

    if (selectedCountEl) {
      selectedCountEl.textContent = totalSelectedCount;
    }

    if (deleteBtn) {
      deleteBtn.disabled = totalSelectedCount === 0;
    }

    if (copySelectedAction) {
      copySelectedAction.disabled = totalSelectedCount === 0;
    }

    const visibleItems = rowsData.filter((it) => it.visible);
    const selectedVisibleCount = visibleItems.filter(
      (it) => it.selected
    ).length;

    if (
      visibleItems.length > 0 &&
      selectedVisibleCount === visibleItems.length
    ) {
      selectAllCheckbox.checked = true;
      selectAllCheckbox.indeterminate = false;
    } else if (selectedVisibleCount > 0) {
      selectAllCheckbox.checked = false;
      selectAllCheckbox.indeterminate = true;
    } else {
      selectAllCheckbox.checked = false;
      selectAllCheckbox.indeterminate = false;
    }
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
    rowsData.forEach((item) => (item.overlapped = false));

    const byInstructor = {};
    rowsData.forEach((it) => {
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
            a.overlapped = b.overlapped = true;
          }
        }
      }
    });

    const byGroupAndTime = {};
    rowsData.forEach((it) => {
      const key = `${it.data["Group"]}_${it.data["Start Time"]}_${it.data["End Time"]}`;
      (byGroupAndTime[key] = byGroupAndTime[key] || []).push(it);
    });

    Object.values(byGroupAndTime).forEach((list) => {
      if (list.length > 1) {
        const instructorsInSlot = new Set(
          list.map((item) => item.data["Instructor"])
        );
        if (instructorsInSlot.size > 1) {
          list.forEach((item) => (item.overlapped = true));
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

    rowsData.forEach((item) => {
      const instructorData = item.data["Instructor"]?.toLowerCase() || "";
      const groupData = item.data["Group"]?.toLowerCase() || "";

      const passInst =
        instructorFilters.length === 0 ||
        instructorFilters.some((filter) => instructorData.includes(filter));
      const passGrp =
        groupFilters.length === 0 ||
        groupFilters.some((filter) => groupData.includes(filter));
      const passOverlap = !onlyOverlap || item.overlapped;

      item.visible =
        item.status === "active" && passInst && passGrp && passOverlap;
    });

    render();
    updateSelectedCount();
  }

  function toggleRowSelection(item, isSelected) {
    item.selected = isSelected;
    const cb = item.row.querySelector(".row-select");
    if (cb) cb.checked = isSelected;
    item.row.classList.toggle("selected-row", isSelected);
  }

  function handleSortClick(e, cfg) {
    const existingIndex = sortCriteria.findIndex(
      (sc) => sc.label === cfg.label
    );

    if (e.shiftKey) {
      if (existingIndex > -1) {
        sortCriteria[existingIndex].direction =
          sortCriteria[existingIndex].direction === "asc" ? "desc" : "asc";
      } else {
        sortCriteria.push({ label: cfg.label, direction: "asc" });
      }
    } else {
      if (existingIndex > -1 && sortCriteria.length === 1) {
        sortCriteria[0].direction =
          sortCriteria[0].direction === "asc" ? "desc" : "asc";
      } else {
        sortCriteria = [{ label: cfg.label, direction: "asc" }];
      }
    }

    sortData();
    updateSortHeaders();
    render();
  }

  function handleRowClick(e) {
    const tr = e.target.closest("tr");
    if (!tr) return;

    const item = rowsData.find((it) => it.row === tr);
    if (!item) return;

    const cb = tr.querySelector(".row-select");
    if (e.target !== cb) {
      cb.checked = !cb.checked;
    }

    toggleRowSelection(item, cb.checked);
    updateSelectedCount();
  }

  async function handleFormSubmit(form, confirmMessage, successCallback) {
    if (confirmMessage && !confirm(confirmMessage)) {
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;

    // if (submitBtn) {
    //   submitBtn.disabled = true;
    //   submitBtn.classList.add("is-loading");
    // }

    try {
      const formData = new FormData(form);
      const response = await fetch(form.action, {
        method: form.method,
        body: formData,
        headers: { Accept: "application/json" },
      });

      // if (!response.ok) {
      //   throw new Error(`Server error: ${response.status}`);
      // }

      if (!response.ok) {
        let errorMsg = `Server error: ${response.status} ${response.statusText}`;
        try {
          const errorResult = await response.json();
          errorMsg = errorResult.message || errorMsg;
        } catch (e) {}
        throw new Error(errorMsg);
      }

      const result = await response.json();
      if (result.success) {
        successCallback(result);
      } else {
        throw new Error(result.message || "Unknown error from server");
      }
    } catch (err) {
      console.error("Fetch error:", err);
      alert(`An error occurred: ${err.message}. Please try again.`);

      if (submitBtn) {
        submitBtn.disabled = false;
      }
    }
  }

  function bindEvents() {
    filterInstructor.addEventListener(
      "keyup",
      utils.debounce(onFilterChange, 120)
    );
    filterGroup.addEventListener("keyup", utils.debounce(onFilterChange, 120));
    filterOverlaps.addEventListener("change", onFilterChange);

    clearFiltersBtn.addEventListener("click", () => {
      selectAllCheckbox.checked = false;
      selectAllCheckbox.indeterminate = false;
      setTimeout(() => {
        onFilterChange();
      }, 0);
    });

    selectAllCheckbox.addEventListener("change", (e) => {
      rowsData.forEach((item) => {
        if (item.visible) toggleRowSelection(item, e.target.checked);
      });
      updateSelectedCount();
    });

    tbody.addEventListener("click", handleRowClick);
    tbody.addEventListener("mouseover", (e) =>
      e.target.closest("tr")?.classList.add("hover-row")
    );
    tbody.addEventListener("mouseout", (e) =>
      e.target.closest("tr")?.classList.remove("hover-row")
    );

    deleteForm?.addEventListener("submit", (e) => {
      e.preventDefault();
      const ids_to_delete = rowsData
        .filter((it) => it.selected)
        .map((it) => it.row.dataset.id);

      if (ids_to_delete.length === 0) return;

      selectedRowsDeleteInput.value = ids_to_delete.join(",");

      handleFormSubmit(deleteForm, null, (result) => {
        const deletedIds = new Set(ids_to_delete);
        rowsData.forEach((item) => {
          if (deletedIds.has(item.row.dataset.id)) {
            item.selected = false;
            item.visible = false;
            item.status = "deleted";
          }
        });

        _calculateAllOverlaps();
        render();
        updateSelectedCount();

        if (restoreBtn) restoreBtn.disabled = false;
      });
    });

    restoreForm?.addEventListener("submit", (e) => {
      e.preventDefault();
      const confirmMsg =
        "This will restore all previously deleted rows. Are you sure?";

      handleFormSubmit(restoreForm, confirmMsg, (result) => {
        alert(result.message);
        location.reload();
      });
    });

    deleteDataForm?.addEventListener("submit", (e) => {
      e.preventDefault();
      const confirmMsg =
        "Are you sure you want to delete all data permanently?";

      handleFormSubmit(deleteDataForm, confirmMsg, (result) => {
        rowsData = [];
        render();
        updateSelectedCount();
        if (restoreBtn) restoreBtn.disabled = true;
      });
    });

    downloadBtn?.addEventListener("click", () => {
      window.location.href = "/download-excel";
    });

    copySelectedAction?.addEventListener("click", () => {
      const selectedItems = rowsData.filter((it) => it.selected);
      if (selectedItems.length === 0) return;

      const dateIdx = columnsConfig.find((c) => c.label === "Date").index;
      const groupIdx = columnsConfig.find((c) => c.label === "Group").index;
      const startIdx = columnsConfig.find(
        (c) => c.label === "Start Time"
      ).index;
      const endIdx = columnsConfig.find((c) => c.label === "End Time").index;

      const textToCopy = selectedItems
        .map((item) => {
          const date = item.row.cells[dateIdx].textContent;
          const group = item.row.cells[groupIdx].textContent;
          const start = item.row.cells[startIdx].textContent;
          const end = item.row.cells[endIdx].textContent;
          return `${date}\n${group}\n${start} - ${end}`;
        })
        .join("\n\n");

      navigator.clipboard
        .writeText(textToCopy)
        .then(() => {
          alert(`Copied ${selectedItems.length} row(s)`);
        })
        .catch((err) => {
          console.error("Error copying selected rows: ", err);
          alert("Error: Could not copy selected rows.");
        });
    });

    copyScheduleAction?.addEventListener("click", () => {
      fetch("/schedule", { method: "GET" })
        .then((res) => {
          if (!res.ok)
            throw new Error(
              "Error copying data. Endpoint /schedule no encontrado?"
            );
          return res.text();
        })
        .then((txt) => {
          navigator.clipboard.writeText(txt);
          alert("Copied Schedule");
        })
        .catch((err) => {
          console.error(err);
          alert("Error: No se pudo copiar. Verifica el endpoint /schedule.");
        });
    });

    copyInstructorsAction?.addEventListener("click", () => {
      const instructorSet = new Set(
        rowsData.map((item) => item.data["Instructor"]?.trim()).filter(Boolean)
      );
      const uniqueInstructors = Array.from(instructorSet);
      const textToCopy = uniqueInstructors.join("\n");
      navigator.clipboard
        .writeText(textToCopy)
        .then(() => {
          alert("Copied Instructors");
        })
        .catch((err) => console.error(err));
    });

    tbody.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      if (!contextMenu) return;

      const tr = e.target.closest("tr");
      if (!tr || tr.id === "noDataRow") return;

      rightClickedRow = tr;
      contextMenu.style.top = `${e.pageY}px`;
      contextMenu.style.left = `${e.pageX}px`;
      contextMenu.style.display = "block";
    });

    window.addEventListener("click", () => {
      if (contextMenu && contextMenu.style.display === "block")
        contextMenu.style.display = "none";
    });

    copyRowAction?.addEventListener("click", () => {
      if (!rightClickedRow) return;

      try {
        const item = rowsData.find((it) => it.row === rightClickedRow);
        if (!item) return;

        const date = item.data["Date"];
        const groupName = item.data["Group"];
        const startTime24h = utils.convertTo24HourFormat(
          item.data["Start Time"]
        );
        const endTime24h = utils.convertTo24HourFormat(item.data["End Time"]);

        const formattedText = `${date}\n${groupName}\n${startTime24h} - ${endTime24h}`;

        navigator.clipboard
          .writeText(formattedText)
          .then(() => console.log("Row copied successfully"))
          .catch((err) => console.error("Error copying row: ", err));
      } catch (err) {
        console.error("Error al copiar fila (revisar 'item.data'):", err);
      }
    });

    deselectAllAction?.addEventListener("click", () => {
      rowsData.forEach((item) => {
        if (item.selected) {
          toggleRowSelection(item, false);
        }
      });
      updateSelectedCount();
    });

    columnsConfig.forEach((cfg) => {
      if (cfg.sortable) {
        cfg.headerEl.style.cursor = "pointer";
        cfg.headerEl.addEventListener("click", (e) => handleSortClick(e, cfg));
      }
    });
  }

  function init(tableSelector) {
    table = document.querySelector(tableSelector);
    if (!table) return;

    tbody = table.tBodies[0];
    headers = Array.from(table.tHead.querySelectorAll("th"));

    contextMenu = document.getElementById("row-context-menu");
    copyRowAction = document.getElementById("copy-row-action");
    deselectAllAction = document.getElementById("deselect-all-action");
    filterInstructor = document.getElementById("filter-instructor");
    filterGroup = document.getElementById("filter-group");
    filterOverlaps = document.getElementById("filter-overlaps");
    clearFiltersBtn = document.querySelector(
      '#filter-form button[type="reset"]'
    );
    selectAllCheckbox = document.getElementById("select-all");
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
    copySelectedAction = document.getElementById("copy-selected-action");
    copyScheduleAction = document.getElementById("copy-schedule-action");
    copyInstructorsAction = document.getElementById("copy-instructors-action");
    selectedCountEl = document.getElementById("stat-selected");
    itemsCountEl = document.getElementById("stat-items");
    overlapCountEl = document.getElementById("stat-overlaps");

    headers.forEach((th) => {
      th.dataset.originalText = th.textContent.trim();
    });

    columnsConfig = headers.map((th, idx) => ({
      label: th.dataset.originalText,
      index: idx,
      parser: /time/i.test(th.dataset.originalText)
        ? utils.parseTimeToMinutes
        : utils.textParser,
      sortable: idx > 0,
      headerEl: th,
    }));

    const startTimeCfg = columnsConfig.find((c) => c.label === "Start Time");
    const endTimeCfg = columnsConfig.find((c) => c.label === "End Time");
    const simpleTimeCfg = columnsConfig.find((c) => c.label === "Time");

    rowsData = Array.from(tbody.rows)
      .map((row, i) => {
        if (row.cells.length < columnsConfig.length) return null;

        const data = {};
        columnsConfig.forEach((cfg) => {
          data[cfg.label] = row.cells[cfg.index]?.textContent.trim() || "";
        });

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
              const startTime24h =
                utils.convertTo24HourFormat(originalStartTime);
              const endTime24h = utils.convertTo24HourFormat(originalEndTime);
              cell.textContent = `${startTime24h} - ${endTime24h}`;
            }
          }
        }

        const cb = row.querySelector(".row-select");
        row.dataset.originalIndex = i;

        return {
          row,
          data,
          visible: true,
          overlapped: false,
          selected: !!cb?.checked,
          originalIndex: i,
          status: "active",
        };
      })
      .filter(Boolean);

    _calculateAllOverlaps();
    bindEvents();
    onFilterChange();
  }

  return { init: init };
})();

export const TableManager = manager;
