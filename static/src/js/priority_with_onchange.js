/** @odoo-module **/

//import { PriorityField, preloadPriority } from "@web/views/fields/priority/priority_field";
//import { registry } from "@web/core/registry";
//
//export class PriorityFieldWithOnchange extends PriorityField {
//    /**
//     * Override updateRecord để sau khi urgentSave,
//     * force trigger onchange cho field này.
//     * Chỉ áp dụng cho widget "priority_onchange" — không ảnh hưởng widget "priority" gốc.
//     */
//    async updateRecord(value) {
//        // Ghi giá trị qua urgentSave như bình thường
//        await this.props.record.update({ [this.props.name]: value });
//        // Force trigger onChange để computed fields recompute trên UI
//        await this.props.record.save({ urgent: false });
//    }
//}
//
//PriorityFieldWithOnchange.template = PriorityField.template;
//
//registry.category("fields").add("priority_onchange", {
//    component: PriorityFieldWithOnchange,
//    preload: preloadPriority,
//    supportedTypes: ["selection"],
//});

/** @odoo-module **/


import { PriorityField } from "@web/views/fields/priority/priority_field";
import { registry } from "@web/core/registry";

export class PriorityFieldWithOnchange extends PriorityField {
    async updateRecord(value) {
        await this.props.record.update({ [this.props.name]: value });
        await this.props.record.save({ urgent: false });
    }
}

registry.category("fields").add("priority_onchange", {
    component: PriorityFieldWithOnchange,
});