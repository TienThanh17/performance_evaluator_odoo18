/** @odoo-module */

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onMounted, onPatched, useRef, xml } from "@odoo/owl";
import {
    parseChildKpiRows,
    renderChildKpiMatrixGrid,
    renderChildTemplateMatrixGrid,
} from "./kpi_child_matrix_utils";

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

registry.category("fields").add("kpi_child_matrix", {
    component: KPIChildMatrixField,
    supportedTypes: ["text", "char"],
});

registry.category("fields").add("kpi_child_template_matrix", {
    component: KPIChildTemplateMatrixField,
    supportedTypes: ["text", "char"],
});
