// slipcover's HTML report script.
//
// Progressive enhancement only: with this file blocked or disabled every row
// is visible, the layout is intact and all navigation still works.  Nothing is
// persisted -- each page load starts from what the report rendered.
//
// The footer totals are server-rendered and are never touched here.  They span
// every measured file, including any that --skip-covered kept out of the table,
// so recomputing them from the visible rows would contradict the percentage in
// the heading.  Filtering and hiding only ever set row.hidden.

"use strict";

(function () {
    const table = document.querySelector("table.index");
    const filter = document.getElementById("filter");
    const hideCovered = document.getElementById("hide_covered");

    // Set below if there is a table to filter; the keyboard handler needs it.
    let refresh = null;

    // -- index table --

    if (table) {
        const headers = Array.from(table.tHead.rows[0].cells);
        const rows = table.querySelector("tbody.rows");
        const empty = table.querySelector("tbody.empty");

        // With --branch there are two extra columns, branches and partial.
        const hasArcs = headers.length === 6;

        // The text a cell sorts and filters by.
        const cellText = (row, column) => row.cells[column].textContent.trim();

        // Numeric columns include the "%" of a coverage cell; parseFloat stops
        // at it.  A cell that isn't a number at all sorts as 0 rather than
        // poisoning every comparison with NaN.
        const sortKey = function (row, column, kind) {
            const text = cellText(row, column);
            if (kind !== "number") {
                return text.toLowerCase();
            }
            const value = parseFloat(text);
            return isNaN(value) ? 0 : value;
        };

        const sortRows = function (column, ascending) {
            const kind = headers[column].dataset.sort;
            const direction = ascending ? 1 : -1;
            // Array.prototype.sort is stable, so rows that tie keep the order
            // they had -- the report's own, by file name.
            const sorted = Array.from(rows.rows).sort(function (a, b) {
                const ka = sortKey(a, column, kind);
                const kb = sortKey(b, column, kind);
                if (ka < kb) return -direction;
                if (ka > kb) return direction;
                return 0;
            });
            sorted.forEach((row) => rows.appendChild(row));
            headers.forEach(function (header, index) {
                header.setAttribute(
                    "aria-sort",
                    index !== column ? "none" : (ascending ? "ascending" : "descending")
                );
            });
        };

        headers.forEach(function (header, column) {
            const button = header.querySelector("button");
            if (!button) {
                return;
            }
            button.addEventListener("click", function () {
                const current = header.getAttribute("aria-sort");
                let ascending;
                if (current === "none") {
                    // Counts are most interesting at their largest, names at A.
                    ascending = header.dataset.sort !== "number";
                } else {
                    ascending = current === "descending";
                }
                sortRows(column, ascending);
            });
        });

        // A row shows only if it passes the filter and the hide-covered box.
        // What the report itself computed, kept verbatim so it can be put back
        // the moment filtering stops.  It can't be recovered by adding rows up:
        // --skip-covered leaves fully covered files out of the table entirely,
        // yet they still count towards the report's own total.
        // Numeric cells only -- cell 0 holds the label element, and writing
        // textContent into it would replace the span and leave `label` pointing
        // at a node no longer in the document.
        const footRow = table.tFoot ? table.tFoot.rows[0] : null;
        const reported = footRow
            ? Array.from(footRow.cells).slice(1).map((cell) => cell.textContent)
            : null;
        const label = footRow ? footRow.querySelector(".total-label") : null;

        // Reserved for genuinely complete/empty coverage, matching _percent_str
        // on the Python side so a subtotal never reads 100% with lines missing.
        const percentStr = function (nom, den) {
            if (den === 0) {
                return "100";
            }
            const rounded = Math.round((100 * nom) / den);
            if (rounded === 100 && nom !== den) {
                return "99";
            }
            if (rounded === 0 && nom !== 0) {
                return "1";
            }
            return String(rounded);
        };

        const num = function (row, name) {
            return parseInt(row.dataset[name], 10) || 0;
        };

        const subtotal = function (visible) {
            let st = 0, ex = 0, br = 0, exbr = 0, pa = 0;
            for (const row of visible) {
                st += num(row, "st");
                ex += num(row, "ex");
                br += num(row, "br");
                exbr += num(row, "exbr");
                pa += num(row, "pa");
            }
            const cells = [String(st), String(st - ex)];
            if (hasArcs) {
                cells.push(String(br), String(pa));
            }
            cells.push(percentStr(ex + exbr, st + br) + "%");
            return cells;
        };

        const applyFilters = function () {
            const needle = filter ? filter.value.trim().toLowerCase() : "";
            const hiding = Boolean(hideCovered && hideCovered.checked);
            const visible = [];
            for (const row of rows.rows) {
                const name = cellText(row, 0).toLowerCase();
                const covered = parseFloat(cellText(row, row.cells.length - 1)) === 100;
                const shown = name.includes(needle) && !(hiding && covered);
                row.hidden = !shown;
                if (shown) {
                    visible.push(row);
                }
            }
            if (empty) {
                // A report with no files at all hasn't been filtered down to
                // nothing, so it doesn't get told that nothing matched.
                empty.hidden = visible.length > 0 || rows.rows.length === 0;
            }
            if (!footRow || !reported) {
                return;
            }
            // Only a filter the user actually applied replaces the reported
            // total, and it says so when it does.  "hide covered" alone doesn't
            // count: with --skip-covered the box is checked from the start.
            const narrowed = needle !== "" || (hiding && !hideCovered.disabled);
            if (narrowed) {
                const cells = subtotal(visible);
                cells.forEach(function (text, index) {
                    footRow.cells[index + 1].textContent = text;
                });
                if (label) {
                    label.textContent = "Shown";
                }
                footRow.classList.add("filtered");
            } else {
                reported.forEach(function (text, index) {
                    footRow.cells[index + 1].textContent = text;
                });
                if (label) {
                    label.textContent = "Total";
                }
                footRow.classList.remove("filtered");
            }
        };
        refresh = applyFilters;

        if (filter) {
            filter.addEventListener("input", applyFilters);
        }
        if (hideCovered) {
            hideCovered.addEventListener("change", applyFilters);
        }
        // The browser can restore a checked box or a typed filter across a
        // reload, so settle the table against the controls as they now are.
        applyFilters();
    }

    // -- keyboard shortcuts --

    const follow = function (id) {
        const link = document.getElementById(id);
        if (link && link.getAttribute("href")) {
            window.location.href = link.href;
        }
    };

    document.addEventListener("keydown", function (event) {
        if (event.ctrlKey || event.altKey || event.metaKey) {
            return;
        }

        const target = event.target;
        const typing =
            target &&
            (target.tagName === "INPUT" ||
                target.tagName === "TEXTAREA" ||
                target.isContentEditable);
        if (typing) {
            // Escape gets you back out of the filter; nothing else steals a
            // keystroke meant for the field.
            if (event.key === "Escape" && filter && target === filter) {
                filter.value = "";
                if (refresh) {
                    refresh();
                }
                filter.blur();
            }
            return;
        }

        switch (event.key) {
            case "f":
                if (filter) {
                    // Or the "f" lands in the field we just focused.
                    event.preventDefault();
                    filter.focus();
                }
                break;
            case "[":
                follow("prevFileLink");
                break;
            case "]":
                follow("nextFileLink");
                break;
            case "u":
                follow("indexLink");
                break;
        }
    });
})();
