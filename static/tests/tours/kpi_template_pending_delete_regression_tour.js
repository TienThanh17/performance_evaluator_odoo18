/** @odoo-module */

import { registry } from "@web/core/registry";
import { stepUtils } from "@web_tour/tour_service/tour_utils";

registry.category("web_tour.tours").add("kpi_template_pending_delete_regression", {
    test: true,
    url: "/odoo",
    steps: () => [
        {
            content: "Open the P3.1.1 page",
            trigger: 'a[role="tab"]:contains("P3.1.1")',
            run: "click",
        },
        {
            content: "Delete the existing child line locally",
            trigger:
                'div[name="kpi_line_p3_individual_ids"] tbody tr.o_data_row:contains("Old Child") .o_list_record_remove button',
            run: "click",
        },
        {
            content: "Open the child KPI popup from the section row",
            trigger:
                'div[name="kpi_line_p3_individual_ids"] tbody tr.o_data_row:contains("TC1 - An Toàn") a:contains("Add KPI")',
            run: "click",
        },
        {
            content: "Fill the new KPI title",
            trigger: 'div.modal div[name="key_performance_area"] input',
            run: "text New Child",
        },
        {
            content: "Choose the scoring formula",
            trigger: 'div.modal div[name="scoring_formula_id"] input',
            run: "text UI Regression Formula",
        },
        {
            content: "Select the custom scoring formula option",
            trigger: '.o-autocomplete--dropdown-item:contains("UI Regression Formula")',
            run: "click",
        },
        ...stepUtils.saveForm(),
        {
            content: "Re-open the P3.1.1 page after reload",
            trigger: 'a[role="tab"]:contains("P3.1.1")',
            run: "click",
        },
        {
            content: "The new child line should be visible",
            trigger:
                'div[name="kpi_line_p3_individual_ids"] tbody tr.o_data_row:contains("New Child")',
            run() {
                const text = document.body.innerText || "";
                if (text.includes("The total weight of child lines under")) {
                    throw new Error("Pending deleted child line is still counted in weight validation.");
                }
                if (text.includes("Old Child")) {
                    throw new Error("Old child line still appears after popup create flow.");
                }
            },
        },
    ],
});
