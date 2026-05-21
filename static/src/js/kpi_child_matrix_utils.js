/** @odoo-module */

import { _t } from "@web/core/l10n/translation";

export function parseChildKpiRows(rawRows) {
    if (!rawRows) {
        return [];
    }
    if (Array.isArray(rawRows)) {
        return rawRows;
    }
    try {
        const rows = JSON.parse(rawRows);
        return Array.isArray(rows) ? rows : [];
    } catch {
        return [];
    }
}

function buildChildKpiMatrix(childRows) {
    const employees = [];
    const employeeMap = new Map();
    const indicators = [];
    const indicatorMap = new Map();

    for (const row of childRows) {
        const employeeKey = String(row.employee_id || row.employee || "-");
        if (!employeeMap.has(employeeKey)) {
            const employee = {
                key: employeeKey,
                name: row.employee || "-",
            };
            employeeMap.set(employeeKey, employee);
            employees.push(employee);
        }

        const indicatorKey = String(row.child_kpi_id || row.child_kpi || "-");
        if (!indicatorMap.has(indicatorKey)) {
            const indicator = {
                key: indicatorKey,
                name: row.child_kpi || "-",
                weight: row.weight || 0,
                scoresByEmployee: {},
            };
            indicatorMap.set(indicatorKey, indicator);
            indicators.push(indicator);
        } else if (!indicatorMap.get(indicatorKey).weight && row.weight) {
            indicatorMap.get(indicatorKey).weight = row.weight;
        }
        indicatorMap.get(indicatorKey).scoresByEmployee[employeeKey] = row.final_rating;
    }

    return { employees, indicators };
}

function buildChildTemplateMatrix(childRows) {
    const templates = [];
    const templateMap = new Map();
    const indicators = [];
    const indicatorMap = new Map();

    for (const row of childRows) {
        const templateKey = String(row.kpi_template_id || row.kpi_template || "-");
        if (!templateMap.has(templateKey)) {
            const template = {
                key: templateKey,
                name: row.kpi_template || "-",
                jobName: row.job_name || "",
            };
            templateMap.set(templateKey, template);
            templates.push(template);
        }

        const indicatorKey = String(row.child_kpi || row.child_kpi_id || "-");
        if (!indicatorMap.has(indicatorKey)) {
            const indicator = {
                key: indicatorKey,
                name: row.child_kpi || "-",
                weight: row.weight || 0,
                cellsByTemplate: {},
            };
            indicatorMap.set(indicatorKey, indicator);
            indicators.push(indicator);
        } else if (!indicatorMap.get(indicatorKey).weight && row.weight) {
            indicatorMap.get(indicatorKey).weight = row.weight;
        }
        indicatorMap.get(indicatorKey).cellsByTemplate[templateKey] = {
            name: row.child_kpi || "-",
            weight: row.weight || 0,
        };
    }

    return { templates, indicators };
}

function formatChildNumber(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number)) {
        return "";
    }
    return number.toFixed(2).replace(/\.?0+$/, "");
}

function formatChildScore(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
        return "-";
    }
    return `${formatChildNumber(number)}đ`;
}

function formatChildWeight(value) {
    const formattedValue = formatChildNumber(value);
    return formattedValue ? `${formattedValue}%` : "-";
}

function appendMatrixCell(grid, text, className = "") {
    const item = document.createElement("span");
    item.className = className;
    item.textContent = text;
    grid.appendChild(item);
    return item;
}

export function renderChildKpiMatrixGrid(container, childRows) {
    const { employees, indicators } = buildChildKpiMatrix(childRows);
    if (!employees.length || !indicators.length) {
        return;
    }

    const grid = document.createElement("div");
    grid.className = "o_kpi_child_inline_grid o_kpi_child_matrix_grid";
    grid.style.gridTemplateColumns = `minmax(220px, 2fr) minmax(90px, 0.6fr) repeat(${employees.length}, minmax(120px, 1fr))`;
    container.appendChild(grid);

    appendMatrixCell(grid, _t("KPI con"), "o_kpi_child_matrix_header o_kpi_child_title");
    appendMatrixCell(grid, _t("Trọng số"), "o_kpi_child_matrix_header o_kpi_child_number");
    for (const employee of employees) {
        appendMatrixCell(
            grid,
            employee.name,
            "o_kpi_child_matrix_header o_kpi_child_employee_header"
        );
    }

    for (const indicator of indicators) {
        appendMatrixCell(grid, `- ${indicator.name}`, "o_kpi_child_title");
        appendMatrixCell(
            grid,
            formatChildWeight(indicator.weight),
            "o_kpi_child_number o_kpi_child_weight"
        );
        for (const employee of employees) {
            const score = indicator.scoresByEmployee[employee.key];
            appendMatrixCell(
                grid,
                score === undefined ? "-" : formatChildScore(score),
                "o_kpi_child_number o_kpi_child_score"
            );
        }
    }
}

export function renderChildTemplateMatrixGrid(container, childRows) {
    const { indicators } = buildChildTemplateMatrix(childRows);
    if (!indicators.length) {
        return;
    }

    const grid = document.createElement("div");
    grid.className = "o_kpi_child_inline_grid o_kpi_child_matrix_grid o_kpi_child_template_matrix_grid";
    grid.style.gridTemplateColumns = "minmax(220px, 2fr) minmax(90px, 0.6fr)";
    container.appendChild(grid);

    appendMatrixCell(grid, "KPI Indicator", "o_kpi_child_matrix_header o_kpi_child_title");
    appendMatrixCell(grid, "Weight", "o_kpi_child_matrix_header o_kpi_child_number");

    for (const indicator of indicators) {
        appendMatrixCell(grid, `- ${indicator.name}`, "o_kpi_child_title");
        appendMatrixCell(
            grid,
            formatChildWeight(indicator.weight),
            "o_kpi_child_number o_kpi_child_weight"
        );
    }
}
