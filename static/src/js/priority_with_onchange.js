/** @odoo-module **/
import { PriorityField } from "@web/views/fields/priority/priority_field";
import { registry } from "@web/core/registry";

export class PriorityFieldWithOnchange extends PriorityField {
    async updateRecord(value) {
        await this.props.record.update({ [this.props.name]: value });
//        await this.props.record.save({ urgent: false });
//
//         // Reload parent record để performance_score trên evaluation được cập nhật
//        const parentRecord = this.props.record.model?.root;
//        if (parentRecord && parentRecord !== this.props.record) {
//            await parentRecord.load();
//        }
    }
}

registry.category("fields").add("priority_onchange", {
    component: PriorityFieldWithOnchange,
});