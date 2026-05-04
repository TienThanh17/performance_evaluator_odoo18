/** @odoo-module */

import { registry } from "@web/core/registry";
import { makeContext } from "@web/core/context";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useService } from "@web/core/utils/hooks";

/**
 * Evaluation lines list renderer:
 * - Section rows (is_section=true) are inline editable and look like headers
 * - Normal KPI rows open the popup form when created via "Add KPI"
 */
class EvaluationListRenderer extends ListRenderer {
    setup() {
        super.setup();

        // Lấy context từ list hiện tại (đã được Odoo parse từ XML)
        const context = this.props.list?.context || {};

        // Đọc tên field từ context, nếu không có thì dùng mặc định
        this.discriminant = context.section_field || "is_section";
        this.titleField = context.title_field || "name"; // Mặc định của Odoo thường là 'name'
    }

    onClickSortColumn(column) {
        // Chặn hoàn toàn hành vi sort khi click vào header
        // Nếu bạn muốn linh hoạt, có thể kiểm tra if(this.props.list...) nhưng 
        // để fix cứng cho widget này, chỉ cần return là đủ.
        return;
    }

    add(params) {
        // Make section creation inline editable
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

class EvaluationOne2ManyField extends X2ManyField {
    static components = {
        ...X2ManyField.components,
        ListRenderer: EvaluationListRenderer,
    };

    static defaultProps = {
        ...X2ManyField.defaultProps,
        editable: "bottom",
    };

    setup() {
        super.setup();
        this.canOpenRecord = true;
        this.orm = useService("orm");
    }

    async onAdd({ context = {}, editable } = {}) {
        const evaluatedContext = makeContext([context]);
        if (evaluatedContext.default_is_section) {
            return super.onAdd({ context, editable });
        }

        const parentId = this.props.record.resId;
        // Put newly created KPI lines at the end by pre-filling a sequence higher than current max.
        // (This is a UX hint; the server-side create() also appends when sequence is not provided.)
        let nextSequence = false;
        try {
            const maxLine = await this.orm.searchRead(
                "hr.performance.evaluation.line",
                [["evaluation_id", "=", parentId]],
                ["sequence"],
                { order: "sequence desc", limit: 1 }
            );
            const currentMax = maxLine?.[0]?.sequence || 0;
            nextSequence = currentMax + 10;
        } catch {
            nextSequence = false;
        }

        const additionalContext = {
            ...(this.props.context || {}),
            ...context,
            // For evaluation lines we link with evaluation_id.
            default_evaluation_id: parentId,
            ...(nextSequence ? { default_sequence: nextSequence } : {}),
            // Keep consistent defaults for new KPI line created via popup.
            // (Mapped lines from template will explicitly provide is_auto.)
            default_is_auto: evaluatedContext.default_is_auto ?? false,
            default_data_source: evaluatedContext.default_data_source ?? "manual",
            //            default_target: evaluatedContext.default_target ?? 100,
        };

        const formViewRef = additionalContext.form_view_ref;
        let formViewId = false;
        if (formViewRef) {
            try {
                formViewId = await this.orm.call("ir.model.data", "_xmlid_to_res_id", [formViewRef, false]);
                if (!formViewId) {
                    formViewId = false;
                }
            } catch {
                formViewId = false;
            }
        }

        const action = {
            type: "ir.actions.act_window",
            res_model: "hr.performance.evaluation.line",
            views: [[formViewId || false, "form"]],
            target: "new",
            context: additionalContext,
        };

        await this.env.services.action.doAction(action, {
            onClose: async () => {
                const root = this.props?.record?.model?.root;
                if (root?.load) {
                    await root.load();
                }
            },
        });
    }
}

registry.category("fields").add("evaluation_one2many", {
    ...x2ManyField,
    component: EvaluationOne2ManyField,
    additionalClasses: [...(x2ManyField.additionalClasses || []), "o_field_one2many"],
});
