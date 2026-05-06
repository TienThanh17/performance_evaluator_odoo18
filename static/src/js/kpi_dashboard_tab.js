/** @odoo-module **/
/**
 * kpi_dashboard_tab.js
 *
 * Mounts the KpiDashboard OWL component inside the "Dashboard" notebook tab
 * of the hr.performance.evaluation form view.
 *
 * Strategy: We patch the FormController to detect when the "kpi_dashboard"
 * page becomes visible, then mount the component once into the placeholder div.
 */

import { KpiDashboard } from "@custom_adecsol_hr_performance_evaluator/js/kpi_dashboard_page";
import { FormController } from "@web/views/form/form_controller";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onWillUnmount, useState } from "@odoo/owl";
import { App } from "@odoo/owl";

// We keep a WeakMap so each form instance gets its own mounted app
const _dashboardApps = new WeakMap();

patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        // Mount/unmount lifecycle hooks
        onMounted(() => this._kpiDashboardOnMounted());
        onWillUnmount(() => this._kpiDashboardOnUnmount());
    },

    _kpiDashboardOnMounted() {
        // Hook into tab changes (Odoo 18 uses data-page-id clicks)
        this.__kpiDashboardTabHandler = (ev) => {
            const tabEl = ev.target.closest('[data-page-id="kpi_dashboard"]');
            if (tabEl) {
                this._mountKpiDashboard();
            }
        };
        this.el?.addEventListener("click", this.__kpiDashboardTabHandler, true);
    },

    _kpiDashboardOnUnmount() {
        this.el?.removeEventListener("click", this.__kpiDashboardTabHandler, true);
        this._destroyKpiDashboard();
    },

    _mountKpiDashboard() {
        if (!this.el) return;
        const placeholder = this.el.querySelector("#kpi_dashboard_mount");
        if (!placeholder) return;

        // Already mounted
        if (_dashboardApps.has(placeholder)) return;

        const evaluationId = this.model.root.resId;
        if (!evaluationId) return;

        const env = this.env;

        const app = new App(KpiDashboard, {
            env,
            props: { evaluationId },
            dev: env.debug,
        });

        app.mount(placeholder);
        _dashboardApps.set(placeholder, app);
    },

    _destroyKpiDashboard() {
        if (!this.el) return;
        const placeholder = this.el.querySelector("#kpi_dashboard_mount");
        if (!placeholder) return;
        const app = _dashboardApps.get(placeholder);
        if (app) {
            app.destroy();
            _dashboardApps.delete(placeholder);
        }
    },
});
