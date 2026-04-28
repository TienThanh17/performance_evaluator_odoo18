/** @odoo-module */

import { registry } from "@web/core/registry";
import { Component, xml, useRef } from "@odoo/owl";
import { usePopover } from "@web/core/popover/popover_hook";

// 1. Component con để hiển thị giao diện chứa nội dung HTML
class HtmlPopoverContent extends Component {
    static template = xml`
        <div class="p-2" style="max-width: 450px; font-size: 0.95em; border: 1px solid #000000;">
            <t t-out="props.htmlContent"/>
        </div>
    `;
}

// 2. Widget hiển thị Icon chấm than
class KpiDescriptionIcon extends Component {
    static template = xml`
        <div t-if="hasDescription" class="text-start">
            <i class="fa fa-exclamation-circle text-primary" 
               t-ref="icon"
               t-on-mouseenter="onMouseEnter"
               t-on-mouseleave="onMouseLeave"
               style="cursor: help; font-size: 1.1rem;"/>
        </div>
    `;
    
    setup() {
        this.iconRef = useRef("icon");
        // Odoo 18: Truyền trực tiếp Component con vào usePopover tại đây
        this.popover = usePopover(HtmlPopoverContent, { position: "top" });
    }

    get hasDescription() {
        const value = this.props.record.data[this.props.name] || "";
        const textOnly = value.replace(/<[^>]*>?/gm, '').trim();
        return textOnly.length > 0;
    }

    get descriptionHTML() {
        return this.props.record.data[this.props.name] || "";
    }

    onMouseEnter(ev) {
        // Odoo 18: Dùng hàm open() và chỉ truyền target + props
        this.popover.open(ev.currentTarget, { 
            htmlContent: this.descriptionHTML 
        });
    }

    onMouseLeave() {
        // Odoo 18: Dùng hàm close() để đóng
        if (this.popover) {
            this.popover.close();
        }
    }
}

// 3. Đăng ký widget vào hệ thống
registry.category("fields").add("kpi_description_icon", {
    component: KpiDescriptionIcon,
});
