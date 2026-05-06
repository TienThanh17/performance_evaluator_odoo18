/** @odoo-module **/
/**
 * kpi_dashboard_page.js  –  Standalone KPI Dashboard Client Action
 *
 * Registered as the "kpi_individual_dashboard" client action tag.
 * Template: static/src/xml/kpi_dashboard_template.xml
 *           "performance_evaluator.KpiDashboardStandalone"
 */

import { Component, onMounted, onWillStart, useRef, useState, useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";   // singleton – no service needed
import { loadJS } from "@web/core/assets";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function formatHour(h) {
    if (h == null) return "--";
    const hours = Math.floor(h);
    const mins = Math.round((h - hours) * 60);
    return hours + ":" + String(mins).padStart(2, "0");
}

const PERIOD_LABELS = {
    monthly: "Monthly",
    quarterly: "Quarterly",
    half_yearly: "Half-Yearly",
    yearly: "Yearly",
};

const COLOR_BLUE = "#3b82f6";
const COLOR_GREEN = "#22c55e";
const COLOR_RED = "#ef4444";
const COLOR_INDIGO = "#6366f1";

// Group that grants manager-level access
const MANAGER_GROUP = "custom_adecsol_hr_performance_evaluator.group_manager";

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────
export class KpiDashboard extends Component {
    static template = "performance_evaluator.KpiDashboardStandalone";
    static props = ["*"]; // client action props

    setup() {
        this.orm = useService("orm");

        this.taskRef = useRef("taskChart");
        this.puncRef = useRef("punctualityChart");
        this.radarRef = useRef("spiderChart");
        this.attendanceRef = useRef("attendanceChart");

        this.state = useState({
            phase: "evals",           // "evals" | "dashboard" | "done" | "error"
            isManager: false,
            employees: [],            // [{id, name}] – only for managers
            selectedEmployeeId: null, // null = current user's employee
            departments: [],             // Thêm: Lưu danh sách phòng ban
            selectedDepartmentId: null,  // Thêm: Phòng ban đang chọn
            filteredEmployees: [],       // Thêm: Nhân viên ĐÃ LỌC theo phòng ban để show ra view
            evaluations: [],
            selectedId: null,
            data: null,
            errorMsg: "",
        });

        this._charts = {};

        onWillStart(async () => {
            await this._loadChartJs();
            // await loadJS("https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js");

            // 1. Check manager group using the user singleton
            const isManager = await user.hasGroup(MANAGER_GROUP);
            this.state.isManager = isManager;

            // 2. If manager, prefetch the employee list
            if (isManager) {
                await this._loadEmployees();
            }

            // 3. Load evaluations (for current user or first employee)
            await this._loadEvaluations();
        });

        onMounted(async () => {
            if (this.state.selectedId) {
                await this._loadDashboard();
            }
        });

        useEffect(
            () => {
                if (this.state.phase === "done" && this.state.data) {
                    this._renderCharts();
                }
            },
            () => [this.state.phase, this.state.data] // Chạy lại effect này nếu phase hoặc data thay đổi
        );
    }

    async _loadChartJs() {
        if (window.Chart) return;
        await new Promise((resolve, reject) => {
            const s = document.createElement("script");
            s.src = "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js";

            s.onload = resolve;
            s.onerror = reject;
            document.head.appendChild(s);
        });
    }

    // ── Data loaders ─────────────────────────────────────────────────────────
    async _loadEmployees() {
        try {
            // 1. Load danh sách phòng ban
            const departments = await this.orm.searchRead(
                "hr.department",
                [["active", "=", true]],
                ["id", "name"],
                { order: "name asc" }
            );
            this.state.departments = departments;
            // 2. Load toàn bộ nhân viên (kèm theo department_id)
            const employees = await this.orm.searchRead(
                "hr.employee",
                [["active", "=", true]],
                ["id", "name", "department_id"],
                { order: "name asc", limit: 500 } // Tăng limit nếu công ty đông
            );
            this.state.employees = employees;
            // 3. Lấy thông tin nhân viên của user đang đăng nhập
            const myEmployee = await this.orm.searchRead(
                "hr.employee",
                [["user_id", "=", user.userId]],
                ["id", "name", "department_id"],
                { limit: 1 }
            );

            if (myEmployee.length) {
                this.state.selectedEmployeeId = myEmployee[0].id;
                // Nếu nhân viên này có phòng ban, set phòng ban mặc định
                if (myEmployee[0].department_id) {
                    this.state.selectedDepartmentId = myEmployee[0].department_id[0];
                }
            }
            // 4. Lọc nhân viên theo phòng ban
            this._filterEmployees();
        } catch (e) {
            // Non-fatal: manager selector just won't appear
            console.warn("KPI Dashboard: could not load employee list", e);
        }
    }
    // Hàm mới: Lọc nhân viên dựa trên phòng ban đang chọn
    _filterEmployees() {
        if (this.state.selectedDepartmentId) {
            this.state.filteredEmployees = this.state.employees.filter(
                emp => emp.department_id && emp.department_id[0] === this.state.selectedDepartmentId
            );
        } else {
            // Nếu chọn "Tất cả phòng ban"
            this.state.filteredEmployees = this.state.employees;
        }

        // Kiểm tra xem selectedEmployeeId hiện tại có nằm trong list vừa lọc không
        const empExists = this.state.filteredEmployees.find(e => e.id === this.state.selectedEmployeeId);

        // Nếu không có, tự động nhảy sang nhân viên đầu tiên của phòng ban đó
        if (!empExists && this.state.filteredEmployees.length > 0) {
            this.state.selectedEmployeeId = this.state.filteredEmployees[0].id;
        } else if (!empExists) {
            this.state.selectedEmployeeId = null; // Phòng ban này không có ai
        }
    }

    async _loadEvaluations() {
        try {
            const fields = [
                "id", "name", "period", "start_date", "end_date",
                "performance_score", "performance_level", "state", "employee_id",
            ];

            // Domain: filter by selected employee (manager) or by current user
            let domain;
            if (this.state.isManager && this.state.selectedEmployeeId) {
                domain = [["employee_id", "=", this.state.selectedEmployeeId]];
            } else {
                domain = [["employee_id.user_id", "=", user.userId]];
            }

            const evals = await this.orm.searchRead(
                "hr.performance.evaluation",
                domain,
                fields,
                { order: "start_date desc", limit: 24 }
            );

            this.state.evaluations = evals;

            if (evals.length > 0) {
                this.state.selectedId = evals[0].id;
                this.state.phase = "dashboard";
            } else {
                this.state.data = null;
                this.state.phase = "done";
            }
        } catch (e) {
            this.state.errorMsg = "Could not load evaluations.";
            this.state.phase = "error";
        }
    }

    async _loadDashboard() {
        this.state.phase = "dashboard";
        this._destroyCharts();
        try {
            const data = await this.orm.call(
                "hr.performance.evaluation",
                "get_dashboard_data",
                [[this.state.selectedId]]
            );
            this.state.data = data;
            this.state.phase = "done";

            console.log('data', data)

            // await Promise.resolve();
            // Ép trình duyệt đợi đến frame tiếp theo (đảm bảo thẻ <canvas> đã xuất hiện trên DOM)
            // await new Promise(resolve => requestAnimationFrame(resolve));

            // this._renderCharts();
        } catch (e) {
            this.state.errorMsg = "Could not load dashboard data.";
            this.state.phase = "error";
        }
    }

    // ── Event handlers ───────────────────────────────────────────────────────
    async onSelectDepartment(ev) {
        const val = ev.target.value;
        // Nếu val rỗng ("") tức là chọn "Tất cả phòng ban"
        this.state.selectedDepartmentId = val ? parseInt(val, 10) : null;

        // Gọi hàm lọc lại danh sách nhân viên
        this._filterEmployees();

        // Reset data và load lại evaluation của nhân viên mới
        this.state.evaluations = [];
        this.state.selectedId = null;
        this.state.data = null;
        await this._loadEvaluations();
        if (this.state.selectedId) {
            await this._loadDashboard();
        }
    }

    async onSelectEmployee(ev) {
        const id = parseInt(ev.target.value, 10);
        if (!id || id === this.state.selectedEmployeeId) return;
        this.state.selectedEmployeeId = id;
        this.state.evaluations = [];
        this.state.selectedId = null;
        this.state.data = null;
        await this._loadEvaluations();
        if (this.state.selectedId) {
            await this._loadDashboard();
        }
    }

    async onSelectEval(ev) {
        const id = parseInt(ev.target.value, 10);
        if (!id || id === this.state.selectedId) return;
        this.state.selectedId = id;
        await this._loadDashboard();
    }

    // ── Computed helpers (called from template) ──────────────────────────────
    get scoreText() {
        return (this.state.data ? this.state.data.performance_score : 0).toFixed(1);
    }

    get scoreRingStyle() {
        const score = this.state.data ? this.state.data.performance_score : 0;
        const pct = Math.min(score * 10, 100);
        const level = this.state.data ? this.state.data.performance_level : "fail";
        const color = level === "excellent" ? COLOR_BLUE
            : level === "pass" ? COLOR_GREEN
                : COLOR_RED;
        return "background: conic-gradient(" + color + " " + pct + "%, #e5e7eb 0)";
    }

    get levelLabel() {
        return this.state.data ? this.state.data.performance_level : "";
    }

    get levelClass() {
        return "o_kpi_level_badge o_kpi_level_" + this.levelLabel;
    }

    varianceClass(row) {
        const positive = row.variance >= 0;
        const good = row.direction === "higher_better" ? positive : !positive;
        return "o_kpi_variance " + (good ? "o_kpi_variance_good" : "o_kpi_variance_bad");
    }

    formatVariance(row) {
        return (row.variance >= 0 ? "+" : "") + row.variance + "%";
    }

    statusClass(row) {
        if (row.final_score >= 9) return "o_kpi_status o_kpi_status_excellent";
        if (row.final_score >= 5) return "o_kpi_status o_kpi_status_pass";
        return "o_kpi_status o_kpi_status_fail";
    }

    statusText(row) {
        if (row.final_score >= 9) return "Excellent";
        if (row.final_score >= 5) return "On Track";
        return "Below Target";
    }

    periodLabel(period) { return PERIOD_LABELS[period] || period; }

    formatHour(h) { return formatHour(h); }

    evalOptionLabel(ev) {
        const period = PERIOD_LABELS[ev.period] || ev.period;
        return ev.name + " — " + period + " (" + ev.start_date + " → " + ev.end_date + ")";
    }

    // ── Chart rendering ──────────────────────────────────────────────────────
    _renderCharts() {
        const Chart = window.Chart;
        const d = this.state.data;
        if (!Chart || !d) return;
        this._destroyCharts();

        // 1. Task Completion
        const taskEl = this.taskRef.el;
        if (taskEl && d.task_completion.labels.length) {
            this._charts.task = new Chart(taskEl, {
                type: "line",
                data: {
                    labels: d.task_completion.labels,
                    datasets: [
                        {
                            label: "On-time %",
                            data: d.task_completion.data,
                            borderColor: COLOR_BLUE,
                            backgroundColor: "rgba(59,130,246,0.15)",
                            fill: true, tension: 0.4, pointRadius: 3, spanGaps: true,
                        },
                        {
                            label: "Target",
                            data: Array(d.task_completion.labels.length).fill(d.task_completion.target),
                            borderColor: COLOR_GREEN, borderDash: [6, 4],
                            borderWidth: 1.5, pointRadius: 0, fill: false,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (c) => c.dataset.label + ": " + (c.parsed.y != null ? c.parsed.y : "--") + "%",
                            },
                        },
                    },
                    scales: {
                        x: { ticks: { maxTicksLimit: 10, font: { size: 10 } }, grid: { display: false } },
                        y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" }, grid: { color: "rgba(0,0,0,0.05)" } },
                    },
                },
            });
        }

        // 2. Punctuality Log
        const puncEl = this.puncRef.el;
        if (puncEl && d.punctuality_log.labels.length) {
            const expectedH = d.punctuality_log.expected_hour || 8;
            const yMin = Math.max(0, Math.floor(expectedH) - 1);
            const yMax = Math.ceil(expectedH) + 4;
            this._charts.punctuality = new Chart(puncEl, {
                type: "line",
                data: {
                    labels: d.punctuality_log.labels,
                    datasets: [
                        {
                            label: "Check-in",
                            data: d.punctuality_log.data,
                            borderColor: COLOR_GREEN,
                            backgroundColor: "rgba(34,197,94,0.12)",
                            fill: true, tension: 0.3, pointRadius: 3, spanGaps: true,
                        },
                        {
                            label: "Start time",
                            data: Array(d.punctuality_log.labels.length).fill(expectedH),
                            borderColor: COLOR_RED, borderDash: [5, 4],
                            borderWidth: 1.5, pointRadius: 0, fill: false,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (c) => {
                                    const v = c.parsed.y;
                                    return c.dataset.label + ": " + (v != null ? formatHour(v) : "--");
                                },
                            },
                        },
                    },
                    scales: {
                        x: { ticks: { maxTicksLimit: 10, font: { size: 10 } }, grid: { display: false } },
                        y: {
                            min: yMin, max: yMax,
                            ticks: { stepSize: 1, callback: (v) => v + "h" },
                            grid: { color: "rgba(0,0,0,0.05)" },
                        },
                    },
                },
            });
        }

        // 3. Spider / Radar
        const radarEl = this.radarRef.el;
        if (radarEl && d.spider_web.labels.length) {
            this._charts.spider = new Chart(radarEl, {
                type: "radar",
                data: {
                    labels: d.spider_web.labels,
                    datasets: [{
                        label: "Score",
                        data: d.spider_web.scores,
                        backgroundColor: "rgba(99,102,241,0.25)",
                        borderColor: COLOR_INDIGO, borderWidth: 2,
                        pointBackgroundColor: COLOR_INDIGO, pointRadius: 4,
                    }],
                },
                options: {
                    responsive: true,
                    plugins: { legend: { display: false } },
                    scales: {
                        r: {
                            min: 0, max: 10,
                            ticks: { stepSize: 2, font: { size: 10 } },
                            pointLabels: { font: { size: 11 } },
                            grid: { color: "rgba(0,0,0,0.07)" },
                        },
                    },
                },
            });
        }

        // 4. Attendance Overview (Doughnut)
        const attendanceEl = this.attendanceRef.el;
        if (attendanceEl && d.attendance_full && d.attendance_full.summary.expected_work_days > 0) {
            const worked = d.attendance_full.summary.worked_days;
            const expected = d.attendance_full.summary.expected_work_days;
            const absent = expected - worked;
            
            this._charts.attendance = new Chart(attendanceEl, {
                type: "doughnut",
                data: {
                    labels: ["Days Present", "Days Absent"],
                    datasets: [{
                        data: [worked, absent],
                        backgroundColor: ["#3b82f6", "#e2e8f0"], // Matching legend color
                        borderWidth: 0,
                        hoverOffset: 4
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '75%', // makes it a thin ring
                    plugins: { 
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (c) => c.label + ": " + c.parsed + " days"
                            }
                        }
                    },
                },
            });
        }
    }

    _destroyCharts() {
        for (const k of Object.keys(this._charts)) {
            try { this._charts[k].destroy(); } catch (_) { }
        }
        this._charts = {};
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Register as client action
// ─────────────────────────────────────────────────────────────────────────────
registry.category("actions").add("kpi_individual_dashboard", KpiDashboard);
