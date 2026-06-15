/** @odoo-module */

import { makeContext } from "@web/core/context";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { ListArchParser } from "@web/views/list/list_arch_parser";
import { Component, onWillRender } from "@odoo/owl";

import { KPIOne2ManyField, KPIListRenderer } from "./kpi_one2many";

export class KpiTemplateTreeHandleField extends Component {
    static template = "web.HandleField";
    static props = {
        ...standardFieldProps,
    };
}

export const kpiTemplateTreeHandleField = {
    component: KpiTemplateTreeHandleField,
    displayName: _t("Handle"),
    supportedTypes: ["integer"],
    isEmpty: () => false,
    listViewWidth: 30,
};

registry
    .category("fields")
    .add("kpi_template_tree_handle", kpiTemplateTreeHandleField);

patch(ListArchParser.prototype, {
    parseFieldNode(node, models, modelName) {
        const result = super.parseFieldNode(node, models, modelName);
        if (result.widget === "kpi_template_tree_handle") {
            result.isHandle = true;
            result.attrs = { ...result.attrs, nolabel: "1" };
        }
        return result;
    },
});

class KpiTemplateTreeListRenderer extends KPIListRenderer {
    static recordRowTemplate =
        "custom_adecsol_hr_performance_evaluator.KpiTemplateTreeListRenderer.RecordRow";

    setup() {
        super.setup();
        onWillRender(() => {
            if (!this.withHandleColumn) {
                this.withHandleColumn = this.columns.some(
                    (column) => column.widget === "kpi_template_tree_handle",
                );
            }
        });
    }

    getSectionItemContext(record) {
        return {
            default_parent_line_id: record.resId || false,
        };
    }

    getSectionSectionContext(record) {
        return {
            default_parent_line_id: record.resId || false,
            default_is_section: true,
            default_display_type: "line_section",
            is_section: true,
            force_popup_section: true,
        };
    }

    getColumnClass(column) {
        const classes = super.getColumnClass(column);
        if (column.widget === "kpi_template_tree_handle") {
            return `${classes.replace(
                "o_kpi_template_tree_handle_cell",
                "o_handle_cell",
            )} o_kpi_template_handle_cell`.trim();
        }
        return classes;
    }

    getCellClass(column, record) {
        const classes = super.getCellClass(column, record);
        if (column.widget === "kpi_template_tree_handle") {
            return `${classes
                .replace("o_kpi_template_tree_handle_cell", "o_handle_cell")
                .replace("o_list_number", "")
                .trim()} o_kpi_template_handle_cell`;
        }
        return classes;
    }

    getParentResId(record) {
        return record.data.parent_line_id?.[0] || false;
    }

    getRecordMaps(records) {
        const recordByLocalId = new Map();
        const recordByResId = new Map();

        for (const record of records) {
            recordByLocalId.set(String(record.id), record);
            recordByResId.set(record.id, record);
            if (record.resId) {
                recordByResId.set(record.resId, record);
            }
        }
        return { recordByLocalId, recordByResId };
    }

    getDepthMap(records, recordByResId) {
        const depthMap = new Map();

        for (const record of records) {
            let depth = 0;
            let ancestorResId = this.getParentResId(record);
            const seenResIds = new Set();

            while (
                ancestorResId &&
                recordByResId.has(ancestorResId) &&
                !seenResIds.has(ancestorResId)
            ) {
                depth += 1;
                seenResIds.add(ancestorResId);
                ancestorResId = this.getParentResId(recordByResId.get(ancestorResId));
            }
            depthMap.set(String(record.id), depth);
        }
        return depthMap;
    }

    getSubtreeEndIndex(records, startIndex, depthMap) {
        const rootDepth = depthMap.get(String(records[startIndex].id)) || 0;
        let endIndex = startIndex;

        for (let index = startIndex + 1; index < records.length; index += 1) {
            const currentDepth = depthMap.get(String(records[index].id)) || 0;
            if (currentDepth <= rootDepth) {
                break;
            }
            endIndex = index;
        }
        return endIndex;
    }

    getSiblingBlocks(records, depthMap, parentResId) {
        const blocks = [];

        for (let index = 0; index < records.length; index += 1) {
            const record = records[index];
            if (this.getParentResId(record) !== parentResId) {
                continue;
            }

            const endIndex = this.getSubtreeEndIndex(records, index, depthMap);
            blocks.push({
                root: record,
                rootLocalId: String(record.id),
                parentResId,
                start: index,
                end: endIndex,
                rows: records.slice(index, endIndex + 1),
            });
            index = endIndex;
        }
        return blocks;
    }

    getBlockByMemberId(blocks) {
        const blockByMemberId = new Map();
        for (const block of blocks) {
            for (const row of block.rows) {
                blockByMemberId.set(String(row.id), block);
            }
        }
        return blockByMemberId;
    }

    getSortableSibling(anchor, direction) {
        let sibling = anchor || null;
        while (sibling && !sibling.dataset?.id) {
            sibling =
                direction === "previous"
                    ? sibling.previousElementSibling
                    : sibling.nextElementSibling;
        }
        return sibling;
    }

    async restoreListOrder() {
        const list = this.props.list;
        await list._sort();
        await list._onUpdate();
    }

    showInvalidMoveWarning() {
        this.notificationService.add(
            _t("You can only move a KPI line among siblings under the same parent."),
            { type: "warning" },
        );
    }

    async sortDrop(dataRowId, params) {
        const { element } = params;
        await this.props.list.leaveEditMode();
        element.classList.remove("o_row_draggable");
        try {
            this.resequencePromise = this.props.list.model.mutex.exec(() =>
                this.resequenceTemplateTree(String(dataRowId), params),
            );
            await this.resequencePromise;
        } finally {
            element.classList.add("o_row_draggable");
        }
    }

    async resequenceTemplateTree(movedLocalId, { previous }) {
        const list = this.props.list;
        const records = [...(list.records || [])];
        const { recordByLocalId, recordByResId } = this.getRecordMaps(records);
        const movedRecord = recordByLocalId.get(String(movedLocalId));
        if (!movedRecord) {
            await this.restoreListOrder();
            return;
        }

        const parentResId = this.getParentResId(movedRecord);
        const parentRecord = parentResId ? recordByResId.get(parentResId) : null;
        const depthMap = this.getDepthMap(records, recordByResId);
        const siblingBlocks = this.getSiblingBlocks(records, depthMap, parentResId);
        const blockByMemberId = this.getBlockByMemberId(siblingBlocks);
        const movedBlock = blockByMemberId.get(String(movedLocalId));
        if (!movedBlock) {
            await this.restoreListOrder();
            return;
        }

        if (siblingBlocks.length <= 1) {
            await this.restoreListOrder();
            return;
        }

        // Match Odoo's native resequence contract: the drop target is the block
        // immediately before the placeholder, calculated before removing the moved block.
        const normalizedPrevious = this.getSortableSibling(previous, "previous");
        const fromIndex = siblingBlocks.findIndex(
            (block) => block.rootLocalId === movedBlock.rootLocalId,
        );
        let toIndex = 0;

        if (normalizedPrevious) {
            const previousLocalId = String(normalizedPrevious.dataset.id || "");
            const isFirstChildSlot =
                parentRecord && previousLocalId === String(parentRecord.id);
            if (!isFirstChildSlot) {
                const previousBlock = blockByMemberId.get(previousLocalId);
                if (!previousBlock || previousBlock.parentResId !== parentResId) {
                    this.showInvalidMoveWarning();
                    await this.restoreListOrder();
                    return;
                }
                if (previousBlock.rootLocalId === movedBlock.rootLocalId) {
                    await this.restoreListOrder();
                    return;
                }

                const targetIndex = siblingBlocks.findIndex(
                    (block) => block.rootLocalId === previousBlock.rootLocalId,
                );
                toIndex = fromIndex > targetIndex ? targetIndex + 1 : targetIndex;
            }
        } else if (parentResId) {
            this.showInvalidMoveWarning();
            await this.restoreListOrder();
            return;
        }

        const reorderedBlocks = [...siblingBlocks];
        const [movedSiblingBlock] = reorderedBlocks.splice(fromIndex, 1);
        reorderedBlocks.splice(toIndex, 0, movedSiblingBlock);
        const oldRootOrder = siblingBlocks
            .map((block) => block.rootLocalId)
            .join(",");
        const newRootOrder = reorderedBlocks
            .map((block) => block.rootLocalId)
            .join(",");
        if (oldRootOrder === newRootOrder) {
            await this.restoreListOrder();
            return;
        }

        const reorderedSegment = [];
        for (const block of reorderedBlocks) {
            reorderedSegment.push(...block.rows);
        }

        const segmentStart = siblingBlocks[0].start;
        const segmentEnd = siblingBlocks[siblingBlocks.length - 1].end;
        const reorderedRecords = [
            ...records.slice(0, segmentStart),
            ...reorderedSegment,
            ...records.slice(segmentEnd + 1),
        ];

        const updates = [];
        for (const [index, record] of reorderedRecords.entries()) {
            const newSequence = (index + 1) * 10;
            if (Number(record.data.sequence || 0) === newSequence) {
                continue;
            }
            updates.push(
                record._update(
                    { sequence: newSequence },
                    // { withoutParentUpdate: true, withoutOnchange: true },
                    { withoutOnchange: true },
                ),
            );
        }

        await Promise.all(updates);
        await this.restoreListOrder();
    }
}

class KpiTemplateTreeOne2ManyField extends KPIOne2ManyField {
    static components = {
        ...KPIOne2ManyField.components,
        ListRenderer: KpiTemplateTreeListRenderer,
    };

    async onAdd({ context = {}, editable } = {}) {
        const normalizedContext = makeContext([this.props.context, context]);
        if (normalizedContext.default_is_section) {
            normalizedContext.force_popup_section = true;
        }
        return super.onAdd({ context: normalizedContext, editable });
    }
}

registry.category("fields").add("kpi_template_tree_one2many", {
    ...x2ManyField,
    component: KpiTemplateTreeOne2ManyField,
    additionalClasses: [
        ...(x2ManyField.additionalClasses || []),
        "o_field_one2many",
    ],
});
