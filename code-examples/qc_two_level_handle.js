/** @odoo-module */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onWillRender } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { ListArchParser } from "@web/views/list/list_arch_parser";
import { QcSectionListRenderer } from "./qc_section_list";

// ---------------------------------------------------------------------------
// Widget: copy y hệt HandleField, chỉ khác tên template
// ---------------------------------------------------------------------------

export class QcTwoLevelHandleField extends Component {
    static template = "web.HandleField";
    static props = {
        ...standardFieldProps,
    };
}

export const qcTwoLevelHandleField = {
    component: QcTwoLevelHandleField,
    displayName: _t("Handle"),
    supportedTypes: ["integer"],
    isEmpty: () => false,
    listViewWidth: 20,
};

registry.category("fields").add("qc_two_level_handle", qcTwoLevelHandleField);

// ---------------------------------------------------------------------------
// Patch arch parser
//   - isHandle = true  : để StaticList nhận ra handleField, canResequenceRows = true
//   - hasLabel = false : ẩn label cột header (giống handle gốc ẩn qua template check)
// ---------------------------------------------------------------------------

patch(ListArchParser.prototype, {
    parseFieldNode(node, models, modelName) {
        const result = super.parseFieldNode(node, models, modelName);
        if (result.widget === "qc_two_level_handle") {
            result.isHandle = true;
            // hasLabel được tính lại trong visitXML từ attrs.nolabel,
            // không đọc result.hasLabel trực tiếp → phải set qua attrs
            result.attrs = { ...result.attrs, nolabel: "1" };
        }
        return result;
    },
});

// ---------------------------------------------------------------------------
// Patch QcSectionListRenderer
//
// Vấn đề gốc: ListRenderer kiểm tra cứng col.widget === "handle" ở 2 chỗ:
//   1. onWillRender → this.withHandleColumn  (dùng render <td> placeholder)
//   2. getCellClass  → thêm o_qc_two_level_handle_cell thay vì o_handle_cell
//      mà useSortable cần selector ".o_handle_cell" để kích hoạt kéo
//
// Fix: thêm onWillRender bổ sung + override getCellClass.
//
// Logic resequence: dùng offset giống handle gốc (chỉ cập nhật slice bị ảnh
// hưởng, offset = min sequence trong slice, gán offset+0, offset+1, ...).
// Tách 2 cấp: kéo section → resequence section_sequence; kéo item → sequence.
// ---------------------------------------------------------------------------

patch(QcSectionListRenderer.prototype, {

    // ---------------------------------------------------------------------------
    // SETUP
    // ---------------------------------------------------------------------------

    setup() {
        super.setup();
        this.orm = useService("orm");
        // Sửa withHandleColumn sau khi base onWillRender chạy
        onWillRender(() => {
            if (!this.withHandleColumn) {
                this.withHandleColumn = this.columns.some(
                    (col) => col.widget === "qc_two_level_handle"
                );
            }
        });
    },

    // ---------------------------------------------------------------------------
    // RENDERING
    // ---------------------------------------------------------------------------

    getColumnClass(column) {
        const classes = super.getColumnClass(column);
        // getColumnClass gán o_qc_two_level_handle_cell lên <th> header
        if (column.widget === "qc_two_level_handle") {
            return classes.replace("o_qc_two_level_handle_cell", "o_handle_cell");
        }
        return classes;
    },

    getCellClass(column, record) {
        const classes = super.getCellClass(column, record);
        if (column.widget === "qc_two_level_handle") {
            // Xóa o_list_number: CSS rule `.o_list_number .o_field_widget:not(.o_field_handle)`
            // sẽ gán display:inline lên wrapper, làm icon mất vertical center.
            // Standard handle tránh được vì wrapper có class o_field_handle (bị exclude).
            return classes
                .replace("o_qc_two_level_handle_cell", "o_handle_cell")
                .replace("o_list_number", "")
                .trim();
        }
        return classes;
    },

    // ---------------------------------------------------------------------------
    // DRAG AND DROP / RESEQUENCE
    // ---------------------------------------------------------------------------

    async sortDrop(dataRowId, { element, previous }) {
        await this.props.list.leaveEditMode();
        element.classList.remove("o_row_draggable");
        const refId = previous ? previous.dataset.id : null;
        try {
            this.resequencePromise = this.props.list.model.mutex.exec(() =>
                this._twoLevelResequence(dataRowId, refId)
            );
            await this.resequencePromise;
        } finally {
            element.classList.add("o_row_draggable");
        }
    },

    async _twoLevelResequence(movedId, refId) {
        const list = this.props.list;
        const records = [...list.records];

        const movedRecord = records.find((r) => r.id === movedId);
        if (!movedRecord) return;

        // Xây dựng thứ tự mới của toàn bộ list sau khi kéo
        const fromIndex = records.findIndex((r) => r.id === movedId);
        let toIndex = 0;
        if (refId !== null) {
            const refIndex = records.findIndex((r) => r.id === refId);
            toIndex = fromIndex > refIndex ? refIndex + 1 : refIndex;
        }
        const reordered = [...records];
        const [moved] = reordered.splice(fromIndex, 1);
        reordered.splice(toIndex, 0, moved);

        if (this.isSection(movedRecord)) {
            await this._resequenceSections(records, reordered, movedId);
        } else {
            await this._resequenceItems(records, reordered, movedRecord);
        }

        await list._sort();
        await list._onUpdate();
    },

    // Tính lại section_sequence cho các section, dùng offset giống handle gốc.
    // Sau đó đồng bộ section_sequence cho item con (stored compute).
    async _resequenceSections(records, reordered, movedId) {
        const oldSections = records.filter((r) => this.isSection(r));
        const newSections = reordered.filter((r) => this.isSection(r));

        const fromIdx = oldSections.findIndex((r) => r.id === movedId);
        const toIdx = newSections.findIndex((r) => r.id === movedId);
        if (fromIdx === -1 || toIdx === -1) return;

        const updatedMap = await this._offsetResequence(
            oldSections, fromIdx, toIdx, "section_sequence"
        );

        // Đồng bộ section_sequence cho item con của các section bị đổi
        const proms = [];
        for (const rec of records) {
            if (!this.isSection(rec) && rec.data.section_id) {
                const parentResId = rec.data.section_id[0];
                const newSeq = updatedMap.get(parentResId);
                if (newSeq !== undefined && rec.data.section_sequence !== newSeq) {
                    proms.push(
                        rec._update({ section_sequence: newSeq }, { withoutParentUpdate: true, withoutOnchange: true })
                    );
                }
            }
        }
        await Promise.all(proms);
    },

    // Tính lại sequence cho các item trong cùng section, dùng offset giống handle gốc.
    async _resequenceItems(records, reordered, movedRecord) {
        const sectionId = movedRecord.data.section_id?.[0] ?? false;
        const inSection = (r) =>
            !this.isSection(r) && (r.data.section_id?.[0] ?? false) === sectionId;

        const oldItems = records.filter(inSection);
        const newItems = reordered.filter(inSection);

        const fromIdx = oldItems.findIndex((r) => r.id === movedRecord.id);
        const toIdx = newItems.findIndex((r) => r.id === movedRecord.id);
        if (fromIdx === -1 || toIdx === -1) return;

        await this._offsetResequence(oldItems, fromIdx, toIdx, "sequence");
    },

    // Resequence giống handle gốc: chỉ cập nhật slice bị ảnh hưởng,
    // offset = min(sequence trong slice), gán offset+0, offset+1, ...
    // Trả về Map<resId, newSequence> của các record đã thay đổi.
    async _offsetResequence(records, fromIdx, toIdx, fieldName) {
        const order = this.props.list.orderBy.find((o) => o.name === fieldName);
        const asc = !order || order.asc;
        const getSeq = (r) => r.data[fieldName];

        const firstIndex = Math.min(fromIdx, toIdx);
        const lastIndex = Math.max(fromIdx, toIdx) + 1;

        // Kiểm tra sequence có bị lộn xộn không, nếu có thì reorder toàn bộ
        let reorderAll = false;
        let lastSeq = (asc ? -1 : 1) * Infinity;
        for (const r of records) {
            const s = getSeq(r);
            if ((asc && lastSeq >= s) || (!asc && lastSeq <= s)) {
                reorderAll = true;
                break;
            }
            lastSeq = s;
        }

        // Áp dụng vị trí mới
        const reordered = [...records];
        const [movedRec] = reordered.splice(fromIdx, 1);
        reordered.splice(toIdx, 0, movedRec);

        // Xác định tập cần cập nhật
        let toReorder = reordered;
        if (!reorderAll) {
            toReorder = toReorder.slice(firstIndex, lastIndex).filter((r) => r.id !== movedRec.id);
            if (fromIdx < toIdx) {
                toReorder.push(movedRec);
            } else {
                toReorder.unshift(movedRec);
            }
        }
        if (!asc) toReorder.reverse();

        const seqs = toReorder.map(getSeq);
        const offset = seqs.length ? Math.min(...seqs) : 0;

        const proms = toReorder.map((r, i) =>
            r._update({ [fieldName]: offset + i }, { withoutParentUpdate: true, withoutOnchange: true })
        );
        await Promise.all(proms);

        return new Map(toReorder.map((r, i) => [r.resId, offset + i]));
    },
});
