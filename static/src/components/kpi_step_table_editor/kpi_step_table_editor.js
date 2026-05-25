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
            rows: parsed.rows,
            error: parsed.error,
            serialized,
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
        this.state.rows.push({
            from: 0,
            to: null,
            score: 0,
            unbounded: this.state.rows.length === 0,
        });
        this._sync();
    }

    removeRow(ev) {
        const index = Number(ev.currentTarget.dataset.index);
        this.state.rows.splice(index, 1);
        this._sync();
    }

    onInput(ev) {
        const index = Number(ev.currentTarget.dataset.index);
        const field = ev.currentTarget.dataset.field;
        const value = ev.currentTarget.value;
        if (!this.state.rows[index]) {
            return;
        }
        if (field === "from" || field === "score") {
            this.state.rows[index][field] = value === "" ? 0 : Number(value);
        } else if (field === "to") {
            this.state.rows[index].to = value === "" ? null : Number(value);
            this.state.rows[index].unbounded = value === "";
        }
        this._sync();
    }

    onToggleUnbounded(ev) {
        const index = Number(ev.currentTarget.dataset.index);
        const checked = ev.currentTarget.checked;
        if (!this.state.rows[index]) {
            return;
        }
        this.state.rows[index].unbounded = checked;
        if (checked) {
            this.state.rows[index].to = null;
        } else if (this.state.rows[index].to === null) {
            this.state.rows[index].to = Number(this.state.rows[index].from || 0) + 1;
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
        const rows = [...this.state.rows].sort(
            (left, right) => Number(left.from || 0) - Number(right.from || 0)
        );
        this.state.rows.splice(0, this.state.rows.length, ...rows);
        const payload = rows.map((row) => ({
            from: Number(row.from || 0),
            to: row.unbounded ? null : Number(row.to),
            score: Number(row.score || 0),
        }));
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
