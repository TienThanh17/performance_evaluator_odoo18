/** @odoo-module */

import { registry } from "@web/core/registry";
import { makeContext } from "@web/core/context";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onPatched, onWillPatch } from "@odoo/owl";
import {
    parseChildKpiRows,
    renderChildKpiMatrixGrid,
    renderChildTemplateMatrixGrid,
} from "./kpi_child_matrix_utils";

/**
 * KPI list renderer:
 * - Section rows (is_section=true) are inline editable and look like headers
 * - Rows keep the default editable flow; Add KPI still opens popup on creation
 */
export class KPIListRenderer extends ListRenderer {
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
        this.scrollSnapshot = null;
        onWillPatch(() => {
            this.captureScrollPosition({ force: false });
            this.removeChildKpiRows();
        });
        onMounted(() => this.renderChildKpiRows());
        onPatched(() => {
            this.renderChildKpiRows();
            this.restoreScrollPosition();
        });
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
        return this.props.editable;
    }

    getScrollableContainers() {
        const containers = [];
        const seen = new Set();
        let el = this.tableRef?.el;

        while (el) {
            const style = window.getComputedStyle(el);
            const canScrollY = /(auto|scroll)/.test(style.overflowY);
            const canScrollX = /(auto|scroll)/.test(style.overflowX);
            if (
                el.scrollTop ||
                el.scrollLeft ||
                (canScrollY && el.scrollHeight > el.clientHeight) ||
                (canScrollX && el.scrollWidth > el.clientWidth)
            ) {
                containers.push(el);
                seen.add(el);
            }
            el = el.parentElement;
        }

        const scrollingElement = document.scrollingElement || document.documentElement;
        if (scrollingElement && !seen.has(scrollingElement)) {
            containers.push(scrollingElement);
        }
        return containers;
    }

    captureScrollPosition({ force = true } = {}) {
        if (!force && this.scrollSnapshot?.length) {
            return;
        }
        this.scrollSnapshot = this.getScrollableContainers().map((el) => ({
            el,
            top: el.scrollTop,
            left: el.scrollLeft,
        }));
    }

    restoreScrollPosition() {
        if (!this.scrollSnapshot?.length) {
            return;
        }
        const snapshot = this.scrollSnapshot;
        const restore = () => {
            for (const item of snapshot) {
                if (item.el.isConnected) {
                    item.el.scrollTop = item.top;
                    item.el.scrollLeft = item.left;
                }
            }
        };
        restore();
        requestAnimationFrame(() => {
            restore();
            requestAnimationFrame(() => {
                restore();
                if (this.scrollSnapshot === snapshot) {
                    this.scrollSnapshot = null;
                }
            });
        });
    }

    focus(el) {
        if (!el) {
            return;
        }
        this.captureScrollPosition({ force: false });
        try {
            el.focus({ preventScroll: true });
        } catch {
            el.focus();
        }
        if (
            ["text", "search", "url", "tel", "password", "textarea"].includes(el.type) &&
            el.selectionStart === el.selectionEnd
        ) {
            el.selectionStart = 0;
            el.selectionEnd = el.value.length;
        }
        this.restoreScrollPosition();
    }

    onClickCapture(record, ev) {
        this.captureScrollPosition({ force: true });
        return super.onClickCapture(record, ev);
    }

    onButtonCellClicked(record, column, ev) {
        this.captureScrollPosition({ force: true });
        try {
            return super.onButtonCellClicked(record, column, ev);
        } finally {
            this.restoreScrollPosition();
        }
    }

    async onCellClicked(record, column, ev) {
        this.captureScrollPosition({ force: true });
        try {
            return await super.onCellClicked(record, column, ev);
        } finally {
            this.restoreScrollPosition();
        }
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
        // Always return the full column list so every row has the same number of <td>
        // as the header <th>, keeping table alignment intact.
        // For section rows, cells of irrelevant fields will render empty naturally;
        // the title (name), weight, and parent_line_id columns will show their values.
        return super.getColumns(record);
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

export class KPIOne2ManyField extends X2ManyField {
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
        // Keep popup support available for x2many flows that call openRecord.
        this.canOpenRecord = true;
        this.orm = useService("orm");
    }

    /**
     * Intercept creation:
     * - Add Section (context default_is_section): inline (super)
     * - Add KPI: open popup form to create
     */
    async onAdd({ context = {}, editable } = {}) {
        context = makeContext([this.props.context, context]);
        const evaluatedContext = context;
        if (
            evaluatedContext.default_is_section &&
            !evaluatedContext.force_popup_section
        ) {
            return super.onAdd({ context, editable });
        }

        const parentField = this.props.context.parent_field || this.props.record.data[this.props.name]?.config?.relationField;
        const additionalContext = {
            ...context,
        };

        const parentId = this.props.record.resId;
        additionalContext[`default_${parentField}`] = parentId;

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

        const model = additionalContext.resModel || this.props.record.data[this.props.name]?.resModel;
        const action = {
            type: "ir.actions.act_window",
            name: evaluatedContext.default_is_section ? "Add Section" : "Add KPI",
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
