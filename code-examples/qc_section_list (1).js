/** @odoo-module */

import { registry } from "@web/core/registry";
import { makeContext } from "@web/core/context";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

import { _t } from "@web/core/l10n/translation";

/**
 * List renderer:
 * - Section rows (is_section=true) are inline editable and look like headers
 * - Question rows (is_section=false) are not inline editable; click opens popup
 */
export class QcSectionListRenderer extends ListRenderer {

    // ---------------------------------------------------------------------------
    // SETUP
    // ---------------------------------------------------------------------------

    setup() {
        super.setup();
        const context = this.props.list?.context || {};
        this.discriminant = context.section_field || "is_section";
        this.titleField = context.title_field || "name";
        this.infoField = context.section_info_field || "frequency_display";
        this.dialogService = useService("dialog");
    }

    // ---------------------------------------------------------------------------
    // HELPERS
    // ---------------------------------------------------------------------------

    isSection(record) {
        return !!record.data?.[this.discriminant];
    }

    getSectionItemContext(record) {
        const pageId = record.data.page_id?.[0] ?? false;
        const sectionId = record.resId;
        return {
            default_page_id: pageId,
            default_section_id: sectionId,
        };
    }

    // ---------------------------------------------------------------------------
    // GETTERS / PROPERTIES
    // ---------------------------------------------------------------------------

    get hideAddItem() {
        return !!(this.props.list?.context?.hide_add_item);
    }

    get canResequenceRows() {
        const { handleField, orderBy } = this.props.list;
        if (!handleField) return false;
        return !orderBy.length || orderBy.some((o) => o.name === handleField);
    }

    // ---------------------------------------------------------------------------
    // RENDERING
    // ---------------------------------------------------------------------------

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
        // Giữ lại cột button/action ở cuối, title span phần còn lại
        const buttonCols = columns.filter(
            (col) => col.type !== "field" && col.type !== "handle"
        );
        const colspan = columns.length - buttonCols.length;
        // Ưu tiên dùng 'name' làm edit proxy khi titleField là computed (không editable),
        // fallback về titleField nếu không tìm thấy 'name' trong allColumns.
        const nameCol = this.titleField !== "name"
            ? this.allColumns.find((col) => col.type === "field" && col.name === "name")
            : null;
        const titleCol = nameCol
            || this.allColumns.find((col) => col.type === "field" && col.name === this.titleField);
        if (!titleCol) return [];
        return [{ ...titleCol, colspan }, ...buttonCols];
    }

    getFormattedValue(column, record) {
        // Section row dùng 'name' làm edit proxy: hiển thị giá trị titleField thay vì name
        if (this.isSection(record) && column.name === "name" && this.titleField !== "name") {
            const base = record.data[this.titleField] || record.data.name || '';
            const infoValue = this.infoField ? record.data[this.infoField] : null;
            return infoValue ? `${base} - ${infoValue}` : base;
        }
        const baseValue = super.getFormattedValue(column, record);
        if (!this.isSection(record) || column.name !== this.titleField || !this.infoField) {
            return baseValue;
        }
        const infoValue = record.data[this.infoField];
        return infoValue ? `${baseValue} - ${infoValue}` : baseValue;
    }

    // ---------------------------------------------------------------------------
    // EVENT HANDLERS
    // ---------------------------------------------------------------------------

    async onDeleteRecord(record) {
        if (this.isSection(record)) {
            return new Promise((resolve) => {
                this.dialogService.add(ConfirmationDialog, {
                    title: _t("Delete Section"),
                    body: _t(
                        'Delete section "%s"? All associated child items will also be deleted.', 
                        record.data[this.titleField]
                    ),
                    confirm: async () => { await super.onDeleteRecord(record); resolve(); },
                    cancel: () => resolve(),
                });
            });
        }
        return super.onDeleteRecord(record);
    }

    onClickSortColumn(_column) {
        return;
    }

    add(params) {
        let editable = false;
        if (params.context && !this.env.isSmall) {
            const evaluatedContext = makeContext([params.context]);
            if (evaluatedContext[`default_${this.discriminant}`]) {
                editable = this.props.editable;
            }
        }
        super.add({ ...params, editable });
    }

    async onCellClicked(record, column, ev) {
        const openOnRowClick = this.props.list?.context?.open_on_row_click !== false;
        if (!this.isSection(record) && openOnRowClick && this.props.list?.context?.form_view_ref) {
            if (ev.target.special_click) {
                return;
            }
            return this.props.openRecord(record);
        }
        return super.onCellClicked(record, column, ev);
    }

    onCellKeydownEditMode(hotkey) {
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
QcSectionListRenderer.recordRowTemplate = "qc.QcSectionListRenderer.RecordRow";

export class QcSectionListField extends X2ManyField {
    static template = "qc.QcSectionListField";
    static components = {
        ...X2ManyField.components,
        ListRenderer: QcSectionListRenderer,
    };

    static defaultProps = {
        ...X2ManyField.defaultProps,
        editable: "bottom",
    };

    // ---------------------------------------------------------------------------
    // SETUP
    // ---------------------------------------------------------------------------

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.canOpenRecord = true;
    }

    // ---------------------------------------------------------------------------
    // ACTIONS
    // ---------------------------------------------------------------------------

    async onAdd({ context = {}, editable } = {}) {
        const addContext = makeContext([context]);

        // Nhánh section: thêm dòng header trực tiếp vào list
        if (addContext.default_is_section) {
            const openSectionFormOnAdd = !!addContext.open_section_form_on_add;

            // Lấy section_sequence lớn nhất để gán default cho section mới.
            const parentId = this.props.record.resId;
            let maxSectionSequence = 0;
            if (parentId) {
                const parentField = this.props.context.parent_field;
                const rows = await this.orm.searchRead(
                    this.list.resModel,
                    [[parentField, '=', parentId]],
                    ['section_sequence'],
                    { order: 'section_sequence desc', limit: 1 },
                );
                maxSectionSequence = rows[0]?.section_sequence || 0;
            } else {
                maxSectionSequence = (this.list.records || []).reduce(
                    (max, r) => Math.max(max, Number(r.data?.section_sequence) || 0), 0
                );
            }

            const editedRecord = this.list.editedRecord;
            if (editedRecord) {
                const proms = [];
                this.list.model.bus.trigger("NEED_LOCAL_CHANGES", { proms });
                await Promise.all([...proms, editedRecord._updatePromise]);
                await this.list.leaveEditMode({ canAbandon: false });
            }

            if (!this.list.editedRecord) {
                const sectionContext = { ...this.props.context, ...addContext, default_section_sequence: maxSectionSequence + 1, default_sequence: 0 };
                if (openSectionFormOnAdd) {
                    // Mở dialog mà không pre-add vào list -- Save mới add, Discard bỏ hẳn.
                    return super.onAdd({ context: sectionContext, editable: false });
                }
                await this.list.addNewRecord({
                    context: sectionContext,
                    mode: "edit",
                    position: editable || "bottom",
                });
            }
            return;
        }

        // Nhánh item: mở form popup
        const parentId = this.props.record.resId;
        const parentField =
            this.props.context.parent_field ||
            this.props.record.data[this.props.name]?.config?.relationField;
        const additionalContext = {
            ...this.props.context,
            ...context,
            [`default_${parentField}`]: parentId,
        };

        // Tính sequence mặc định: lấy sequence lớn nhất trong section + 1
        // để item mới được xếp sau item cuối cùng của cùng section_id.
        const sectionId = addContext.default_section_id;
        if (sectionId) {
            const [itemRows, sectionRows] = await Promise.all([
                this.orm.searchRead(
                    this.list.resModel,
                    [['section_id', '=', sectionId], ['is_section', '=', false]],
                    ['sequence'],
                    { order: 'sequence desc', limit: 1 },
                ),
                this.orm.read(this.list.resModel, [sectionId], ['section_sequence']),
            ]);
            additionalContext.default_sequence = (itemRows[0]?.sequence || 0) + 1;
            additionalContext.default_section_sequence = sectionRows[0]?.section_sequence || 0;
        }

        return super.onAdd({ context: additionalContext, editable: false });
    }

    async openRecord(record) {
        if (this.canOpenRecord) {
            return this._openRecord({
                record,
                context: this.props.context,
                mode: this.props.readonly ? "readonly" : "edit",
                title: record?.data?.name || _t("Inspection Entry"),
            });
        }
    }
}

registry.category("fields").add("qc_section_list", {
    ...x2ManyField,
    component: QcSectionListField,
    additionalClasses: [...(x2ManyField.additionalClasses || []), "o_field_one2many"],
});
