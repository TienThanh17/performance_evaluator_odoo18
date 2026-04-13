/** @odoo-module */

import { registry } from "@web/core/registry";
import { makeContext } from "@web/core/context";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useService } from "@web/core/utils/hooks";

/**
 * KPI list renderer:
 * - Section rows (is_section=true) are inline editable and look like headers
 * - KPI rows (is_section=false) are not inline editable; click opens popup
 */
class KPIListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.discriminant = "is_section";
        this.titleField = "key_performance_area";
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
        return this.isSection(record) && this.props.editable;
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
        const additionalContext = {
            ...(this.props.context || {}),
            ...context,
            default_kpi_id: parentId,
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

        const action = {
            type: "ir.actions.act_window",
            res_model: "hr.kpi.line",
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


