/** @odoo-module */

import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_service/tour_utils";

registry.category("web_tour.tours").add("department_kpi_template_popup_sync_regression", {
    test: true,
    url: "/odoo",
    steps: () => [
        {
            content: "Open the P3.1.2 page",
            trigger: 'a[role="tab"]:contains("P3.1.2")',
            run: "click",
        },
        {
            content: "Delete the first old child locally",
            trigger:
                'div[name="kpi_line_ids"] tbody tr.o_data_row:contains("Dept Old Child 1") .o_list_record_remove button',
            run: "click",
        },
        {
            content: "Delete the second old child locally",
            trigger:
                'div[name="kpi_line_ids"] tbody tr.o_data_row:contains("Dept Old Child 2") .o_list_record_remove button',
            run: "click",
        },
        {
            content: "Delete the third old child locally",
            trigger:
                'div[name="kpi_line_ids"] tbody tr.o_data_row:contains("Dept Old Child 3") .o_list_record_remove button',
            run: "click",
        },
        {
            content: "Delete the fourth old child locally",
            trigger:
                'div[name="kpi_line_ids"] tbody tr.o_data_row:contains("Dept Old Child 4") .o_list_record_remove button',
            run: "click",
        },
        {
            content: "Delete the fifth old child locally",
            trigger:
                'div[name="kpi_line_ids"] tbody tr.o_data_row:contains("Dept Old Child 5") .o_list_record_remove button',
            run: "click",
        },
        {
            content: "Open the child KPI popup from the section row",
            trigger:
                'div[name="kpi_line_ids"] tbody tr.o_data_row:contains("TC1 - An Toàn") a:contains("Add KPI")',
            run: "click",
        },
        {
            content: "Fill the replacement KPI title",
            trigger: 'div.modal div[name="name"] input',
            run: "text Dept Replacement Child",
        },
        {
            content: "Choose the scoring formula",
            trigger: 'div.modal div[name="scoring_formula_id"] input',
            run: "text UI Department Regression Formula",
        },
        {
            content: "Select the custom scoring formula option",
            trigger: '.o-autocomplete--dropdown-item:contains("UI Department Regression Formula")',
            run: "click",
        },
        {
            content: "Set the replacement child weight",
            trigger: 'div.modal div[name="weight"] input',
            run: "text 10",
        },
        ...stepUtils.saveForm(),
        {
            content: "Re-open the P3.1.2 page after reload",
            trigger: 'a[role="tab"]:contains("P3.1.2")',
            run: "click",
        },
        {
            content: "The replacement child line should be visible without stale weight errors",
            trigger:
                'div[name="kpi_line_ids"] tbody tr.o_data_row:contains("Dept Replacement Child")',
            run() {
                const text = document.body.innerText || "";
                if (text.includes("The total weight of child lines under")) {
                    throw new Error("Popup create still validates against stale department child rows.");
                }
                for (const label of [
                    "Dept Old Child 1",
                    "Dept Old Child 2",
                    "Dept Old Child 3",
                    "Dept Old Child 4",
                    "Dept Old Child 5",
                ]) {
                    if (text.includes(label)) {
                        throw new Error(`Deleted department child line still appears after popup create flow: ${label}`);
                    }
                }
            },
        },
    ],
});
