/** @odoo-module */

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onWillUpdateProps, useState } from "@odoo/owl";

export class KpiStepTableEditor extends Component {
    static template = "custom_adecsol_hr_performance_evaluator.KpiStepTableEditor";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this._nextRowId = 1;
        this.state = useState(this._buildState(this.props));
        onWillUpdateProps((nextProps) => {
            const serialized = nextProps.record.data[nextProps.name] || "[]";
            if (serialized !== this.state.serialized) {
                Object.assign(this.state, this._buildState(nextProps));
            }
        });
    }

    _buildState(props) {
        const serialized = props.record.data[props.name] || "[]";
        const parsed = this._parseRows(serialized);
        return {
            rows: parsed.rows.map((row) => this._makeRow(row)),
            error: parsed.error,
            serialized,
        };
    }

    _makeRow(row = {}) {
        return {
            _rowId: this._nextRowId++,
            from: row.from ?? 0,
            to: row.to ?? null,
            score: row.score ?? 0,
            unbounded: row.unbounded ?? (row.to === null || row.to === undefined),
        };
    }

    _parseRows(value) {
        try {
            const data = JSON.parse(value || "[]");
            const rows = Array.isArray(data)
                ? data.map((row) => ({
                      from: row.from ?? 0,
                      to: row.to,
                      score: row.score ?? 0,
                      unbounded: row.to === null || row.to === undefined,
                  }))
                : [];
            return { rows, error: "" };
        } catch {
            return { rows: [], error: "JSON hiện tại không hợp lệ." };
        }
    }

    get scoreBase() {
        return this.props.record.data.score_scale_base || 10;
    }

    get readonlyRows() {
        return this._parseRows(this.props.record.data[this.props.name] || "[]").rows;
    }

    addRow() {
        this.state.rows.push(
            this._makeRow({
                from: 0,
                to: null,
                score: 0,
                unbounded: this.state.rows.length === 0,
            })
        );
        this._sync();
    }

    removeRow(ev) {
        const rowId = Number(ev.currentTarget.dataset.rowId);
        const index = this.state.rows.findIndex((row) => row._rowId === rowId);
        if (index === -1) {
            return;
        }
        this.state.rows.splice(index, 1);
        this._sync();
    }

    onInput(ev) {
        const rowId = Number(ev.currentTarget.dataset.rowId);
        const field = ev.currentTarget.dataset.field;
        const value = ev.currentTarget.value;
        const row = this.state.rows.find((item) => item._rowId === rowId);
        if (!row) {
            return;
        }
        if (field === "from" || field === "score") {
            row[field] = value === "" ? 0 : Number(value);
        } else if (field === "to") {
            row.to = value === "" ? null : Number(value);
            row.unbounded = value === "";
        }
        this._sync();
    }

    onToggleUnbounded(ev) {
        const rowId = Number(ev.currentTarget.dataset.rowId);
        const checked = ev.currentTarget.checked;
        const row = this.state.rows.find((item) => item._rowId === rowId);
        if (!row) {
            return;
        }
        row.unbounded = checked;
        if (checked) {
            row.to = null;
        } else if (row.to === null) {
            row.to = Number(row.from || 0) + 1;
        }
        this._sync();
    }

    _validateRows(rows) {
        for (const row of rows) {
            const lower = Number(row.from || 0);
            const score = Number(row.score || 0);
            const upper = row.to === null ? null : Number(row.to);
            if (upper !== null && upper <= lower) {
                return "Giá trị 'Đến' phải lớn hơn 'Từ'.";
            }
            if (score < 0 || score > this.scoreBase) {
                return `Điểm phải nằm trong khoảng 0 - ${this.scoreBase}.`;
            }
        }
        return "";
    }

    _sync() {
        const payload = this.state.rows
            .map((row) => ({
                from: Number(row.from || 0),
                to: row.unbounded ? null : Number(row.to),
                score: Number(row.score || 0),
            }))
            .sort((left, right) => left.from - right.from);
        this.state.error = this._validateRows(payload);
        const serialized = JSON.stringify(payload);
        this.state.serialized = serialized;
        this.props.record.update({ [this.props.name]: serialized });
    }
}

export const kpiStepTableEditor = {
    component: KpiStepTableEditor,
    supportedTypes: ["text"],
};

registry.category("fields").add("kpi_step_table_editor", kpiStepTableEditor);
