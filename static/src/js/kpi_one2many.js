/** @odoo-module */

import { registry } from "@web/core/registry";
import { makeContext } from "@web/core/context";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { ListRenderer } from "@web/views/list/list_renderer";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { Component, onMounted, onPatched, onWillPatch, useRef, xml } from "@odoo/owl";

function parseChildKpiRows(rawRows) {
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
    // scale 10
    // return `${formatChildNumber(number * 10)}đ`;
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

function renderChildKpiMatrixGrid(container, childRows) {
    const { employees, indicators } = buildChildKpiMatrix(childRows);
    if (!employees.length || !indicators.length) {
        return;
    }

    const grid = document.createElement("div");
    grid.className = "o_kpi_child_inline_grid o_kpi_child_matrix_grid";
    grid.style.gridTemplateColumns = `minmax(220px, 2fr) minmax(90px, 0.6fr) repeat(${employees.length}, minmax(120px, 1fr))`;
    container.appendChild(grid);

    appendMatrixCell(grid, "KPI Indicator", "o_kpi_child_matrix_header o_kpi_child_title");
    appendMatrixCell(grid, "Weight", "o_kpi_child_matrix_header o_kpi_child_number");
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

function renderChildTemplateMatrixGrid(container, childRows) {
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

/**
 * KPI list renderer:
 * - Section rows (is_section=true) are inline editable and look like headers
 * - KPI rows (is_section=false) are not inline editable; click opens popup
 */
class KPIListRenderer extends ListRenderer {
    setup() {
        super.setup();

        // Lấy context từ list hiện tại (đã được Odoo parse từ XML)
        const context = this.props.list?.context || {};
//        console.log("class KPIListRenderer this.props:", this.props);
        // Đọc tên field từ context, nếu không có thì dùng mặc định
        this.discriminant = context.section_field || "is_section";
        this.titleField = context.title_field || "name"; // Mặc định của Odoo thường là 'name'

//        console.log("KPIListRenderer setup 1:", { section_field: context.section_field, title_field: context.title_field });
//        console.log("KPIListRenderer setup 2:", { discriminant: this.discriminant, titleField: this.titleField });
        onWillPatch(() => this.removeChildKpiRows());
        onMounted(() => this.renderChildKpiRows());
        onPatched(() => this.renderChildKpiRows());
    }

    onClickSortColumn(column) {
        return;
    }

    add(params) {
        // Make section creation inline editable (like slide_category_one2many)
        let editable = false;
        if (params.context && !this.env.isSmall) {
            const evaluatedContext = makeContext([params.context]);
            if (evaluatedContext[`default_${this.discriminant}`]) {
                editable = this.props.editable;
            }
        }
        super.add({ ...params, editable });
    }

    isSection(record) {
        return !!record.data?.[this.discriminant];
    }

    isInlineEditable(record) {
        // Only sections are inline editable
        return this.props.editable;
    }

    getChildKpiRows(record) {
        return parseChildKpiRows(record.data?.child_line_rows_json);
    }

    getChildTemplateRows(record) {
        return parseChildKpiRows(record.data?.child_template_rows_json);
    }

    removeChildKpiRows() {
        const tbody = this.tableRef?.el?.querySelector("tbody");
        if (!tbody) {
            return;
        }
        tbody.querySelectorAll(".o_kpi_child_inline_row").forEach((row) => row.remove());
    }

    renderChildKpiRows() {
        const tbody = this.tableRef?.el?.querySelector("tbody");
        if (!tbody || this.props.list?.isGrouped) {
            return;
        }
        this.removeChildKpiRows();

        for (const record of this.props.list.records || []) {
            if (this.isSection(record)) {
                continue;
            }
            const childRows = this.getChildKpiRows(record);
            const childTemplateRows = childRows.length ? [] : this.getChildTemplateRows(record);
            if (!childRows.length && !childTemplateRows.length) {
                continue;
            }

            const parentRow = [...tbody.querySelectorAll("tr.o_data_row")].find(
                (row) => row.dataset.id === String(record.id)
            );
            if (!parentRow) {
                continue;
            }

            const matrixRow = this.makeChildKpiMatrixRow({
                childRows,
                childTemplateRows,
                colSpan: parentRow.children.length || 1,
            });
            parentRow.insertAdjacentElement("afterend", matrixRow);
        }
    }

    makeChildKpiMatrixRow({ childRows = [], childTemplateRows = [], colSpan = 1 }) {
        const tr = document.createElement("tr");
        tr.className = "o_kpi_child_inline_row o_kpi_child_inline_data_row";

        const td = document.createElement("td");
        td.colSpan = colSpan;
        td.className = "o_kpi_child_inline_cell";
        tr.appendChild(td);

        if (childRows.length) {
            renderChildKpiMatrixGrid(td, childRows);
        } else {
            renderChildTemplateMatrixGrid(td, childTemplateRows);
        }

        return tr;
    }

    getRowClass(record) {
        const classNames = super.getRowClass(record).split(" ");
        if (this.isSection(record)) {
            classNames.push("o_is_section", "fw-bold");
        }
        return classNames.join(" ");
    }

    getColumns(record) {
        const columns = super.getColumns(record);
        if (!this.isSection(record)) {
            return columns;
        }
        // For section rows, keep only handle + title (colspan)
        const sectionColumns = columns.filter((col) => col.widget === "handle");
        const colspan = columns.length - sectionColumns.length;
        const titleCol = columns.find((col) => col.type === "field" && col.name === this.titleField);
        if (titleCol) {
            sectionColumns.push({ ...titleCol, colspan });
        }
        return sectionColumns;
    }

    onCellKeydownEditMode(hotkey) {
        // On section inline edit: Enter should validate and leave edit mode (no newline)
        switch (hotkey) {
            case "enter":
            case "tab":
            case "shift+tab": {
                this.props.list.leaveEditMode();
                return true;
            }
        }
        return super.onCellKeydownEditMode(...arguments);
    }
}

class KPIOne2ManyField extends X2ManyField {
    static components = {
        ...X2ManyField.components,
        ListRenderer: KPIListRenderer,
    };

    static defaultProps = {
        ...X2ManyField.defaultProps,
        editable: "bottom",
    };

    setup() {
        super.setup();
        // We want to be able to open a record when clicking on KPI rows
        this.canOpenRecord = true;
        this.orm = useService("orm");
    }

    /**
     * Intercept creation:
     * - Add Section (context default_is_section): inline (super)
     * - Add KPI: open popup form to create
     */
    async onAdd({ context = {}, editable } = {}) {
        const evaluatedContext = makeContext([context]);
        if (evaluatedContext.default_is_section) {
            return super.onAdd({ context, editable });
        }

        const parentId = this.props.record.resId;
        const parentField = this.props.context.parent_field || this.props.record.data[this.props.name]?.config?.relationField;
        const additionalContext = {
            ...(this.props.context || {}),
            ...context,
            [`default_${parentField}`]: parentId,
        };

        // If the XML context provides a form view xmlid, use it.
        // (We don't hardcode it here to keep the widget reusable.)
        const formViewRef = additionalContext.form_view_ref;

        // Odoo actions expect numeric view ids, not xmlids.
        // Passing an xmlid (string) triggers a server crash: "Expected singleton" on ir.ui.view.
        let formViewId = false;
        if (formViewRef) {
             try {
                // Odoo 18: public method is _xmlid_to_res_id (xmlid_to_res_id was removed).
                // Returns 0/false when not found (depending on server).
                formViewId = await this.orm.call(
                    "ir.model.data",
                    "_xmlid_to_res_id",
                    [formViewRef, false]
                );
                // Normalize falsy values
                if (!formViewId) {
                    formViewId = false;
                }
            } catch {
                formViewId = false;
            }
        }

        console.log('this.props', this.props)

        const model = additionalContext.resModel || this.props.record.data[this.props.name]?.resModel;
        const action = {
            type: "ir.actions.act_window",
            name: "Add KPI",
            res_model: model,
            views: [[formViewId || false, "form"]],
            target: "new",
            context: additionalContext,
        };

        await this.env.services.action.doAction(action, {
            onClose: async () => {
                // Ensure we leave any edit mode in the list (sections are inline editable)
                // and refresh the x2many display. We don't force a full form reload here.
                if (this.props?.record?.model?.root) {
                    await this.props.record.model.root.load();
                }
            },
        });

//        // ==========================================
//        // FIX ODOO 18: Lấy list object từ widget
//        // ==========================================
//        const list = this.list || this.props.record.data[this.props.name];
//
//        // 2. Tạo record ảo trong bộ nhớ của list
//        const record = await list.addNewRecord({ context: additionalContext });
//
//        let isSaved = false;
//
//        // 3. Mở Dialog với record ảo vừa tạo
//        this.env.services.dialog.add(FormViewDialog, {
//            resModel: list.resModel,
//            resId: false,
//            record: record, // Ép Dialog dùng record ảo
//            context: additionalContext,
//            viewId: formViewId || false,
//            onRecordSaved: async () => {
//                isSaved = true;
//            },
//        }, {
//            onClose: async () => {
//                // Nếu đóng form mà chưa save, dọn dẹp record ảo để không bị dòng trống
//                if (!isSaved) {
//                    try {
//                        // Odoo 18 Data Model xử lý xóa record chưa lưu
//                        if (typeof record.discard === 'function') {
//                            await record.discard();
//                        } else if (typeof list.removeRecord === 'function') {
//                            await list.removeRecord(record);
//                        } else {
//                            // Fallback thủ công
//                            const index = list.records.indexOf(record);
//                            if (index > -1) {
//                                list.records.splice(index, 1);
//                            }
//                        }
//                    } catch (e) {
//                        console.warn("Could not remove the empty record");
//                    }
//                }
//            }
//        });
    }
}

class KPIChildMatrixField extends Component {
    static template = xml/* xml */ `
        <div class="o_kpi_child_inline_row o_kpi_child_inline_data_row o_kpi_child_field_widget">
            <div t-ref="matrixRoot" class="o_kpi_child_inline_cell"></div>
        </div>
    `;
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.matrixRoot = useRef("matrixRoot");
        onMounted(() => this.renderMatrix());
        onPatched(() => this.renderMatrix());
    }

    renderMatrix() {
        const container = this.matrixRoot.el;
        if (!container) {
            return;
        }
        container.replaceChildren();
        const childRows = parseChildKpiRows(this.props.record.data?.[this.props.name]);
        renderChildKpiMatrixGrid(container, childRows);
    }
}

class KPIChildTemplateMatrixField extends Component {
    static template = xml/* xml */ `
        <div class="o_kpi_child_inline_row o_kpi_child_inline_data_row o_kpi_child_field_widget">
            <div t-ref="matrixRoot" class="o_kpi_child_inline_cell"></div>
        </div>
    `;
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.matrixRoot = useRef("matrixRoot");
        onMounted(() => this.renderMatrix());
        onPatched(() => this.renderMatrix());
    }

    renderMatrix() {
        const container = this.matrixRoot.el;
        if (!container) {
            return;
        }
        container.replaceChildren();
        const childRows = parseChildKpiRows(this.props.record.data?.[this.props.name]);
        renderChildTemplateMatrixGrid(container, childRows);
    }
}

/**
 * KPI template widget (hr.kpi.line only)
 */
registry.category("fields").add("kpi_one2many", {
    ...x2ManyField,
    component: KPIOne2ManyField,
    additionalClasses: [...(x2ManyField.additionalClasses || []), "o_field_one2many"],
});

registry.category("fields").add("kpi_child_matrix", {
    component: KPIChildMatrixField,
    supportedTypes: ["text", "char"],
});

registry.category("fields").add("kpi_child_template_matrix", {
    component: KPIChildTemplateMatrixField,
    supportedTypes: ["text", "char"],
});
