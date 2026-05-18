/** @odoo-module **/
/**
 * kpi_dashboard_page.js  –  Standalone KPI Dashboard Client Action
 *
 * Registered as the "kpi_individual_dashboard" client action tag.
 * Template: static/src/xml/kpi_dashboard_template.xml
 *           "performance_evaluator.KpiDashboardStandalone"
 */

import {
    Component,
    onMounted,
    onWillStart,
    useRef,
    useState,
    useEffect,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user"; // singleton – no service needed
import { loadJS } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";

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
    monthly: _t("Monthly"),
    quarterly: _t("Quarterly"),
    half_yearly: _t("Half-Yearly"),
    yearly: _t("Yearly"),
};

const COLOR_BLUE = "#3b82f6";
const COLOR_GREEN = "#22c55e";
const COLOR_RED = "#ef4444";
const COLOR_INDIGO = "#6366f1";

// Group that grants manager-level access
const EMPLOYEE_GROUP = "custom_adecsol_hr_performance_evaluator.group_employee";
const MANAGER_GROUP = "custom_adecsol_hr_performance_evaluator.group_manager";
const HR_GROUP = "custom_adecsol_hr_performance_evaluator.group_hr";
const ADMIN_GROUP = "custom_adecsol_hr_performance_evaluator.group_admin";

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────
export class KpiDashboard extends Component {
    static template = "performance_evaluator.KpiDashboardStandalone";
    static props = ["*"]; // client action props

    setup() {
        this.orm = useService("orm");

        this.doneTasksRef = useRef("doneTasksChart");
        this.taskRef = useRef("taskChart");
        this.puncRef = useRef("punctualityChart");
        this.radarRef = useRef("spiderChart");
        this.attendanceRef = useRef("attendanceChart");

        // 1. Lấy context từ action props (bắt lỗi an toàn nếu mở trực tiếp không qua nút bấm)
        const actionContext = this.props.action?.context || {};

        // 2. Hứng ID nhân viên (nếu không có thì trả về false để load tất cả)
        const passedEmployeeId = actionContext.default_employee_id || false;
        const passedEvaluationId = actionContext.default_evaluation_id || false;

        this.state = useState({
            employee_id: passedEmployeeId, // Dashboard sẽ lấy ID này để gọi xuống Python filter data
            passedEvaluationId: passedEvaluationId,
            phase: "evals", // "evals" | "dashboard" | "done" | "error"
            isEmployee: false,
            isManager: false,
            isHR: false,
            isAdmin: false,
            employees: [], // [{id, name}] – only for managers
            selectedEmployeeId: null, // null = current user's employee
            departments: [], // Thêm: Lưu danh sách phòng ban
            selectedDepartmentId: null, // Thêm: Phòng ban đang chọn
            filteredEmployees: [], // Thêm: Nhân viên ĐÃ LỌC theo phòng ban để show ra view
            evaluations: [],
            selectedEvaluationId: null,
            data: null,
            errorMsg: "",
        });

        this._charts = {};

        onWillStart(async () => {
            await this._loadChartJs();
            // await loadJS("https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js");

            // Chạy song song tất cả các kiểm tra quyền
            const [isEmployee, isManager, isHR, isAdmin] = await Promise.all([
                user.hasGroup(EMPLOYEE_GROUP),
                user.hasGroup(MANAGER_GROUP),
                user.hasGroup(HR_GROUP),
                user.hasGroup(ADMIN_GROUP),
            ]);

            Object.assign(this.state, { isEmployee, isManager, isHR, isAdmin });

            // 2. If manager, prefetch the employee list
            if (this.state.isManager || this.state.isHR || this.state.isAdmin) {
                await this._loadEmployees();
            }

            // 3. Load evaluations (for current user or first employee)
            await this._loadEvaluations();
        });

        onMounted(async () => {
            if (this.state.selectedEvaluationId) {
                await this._loadDashboard();
            }
        });

        useEffect(
            () => {
                if (this.state.phase === "done" && this.state.data) {
                    this._renderCharts();
                }
            },
            () => [this.state.phase, this.state.data], // Chạy lại effect này nếu phase hoặc data thay đổi
        );
    }

    async _loadChartJs() {
        if (window.Chart) return;
        await new Promise((resolve, reject) => {
            const s = document.createElement("script");
            s.src =
                "https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js";

            s.onload = resolve;
            s.onerror = reject;
            document.head.appendChild(s);
        });
    }

    // ── Data loaders ─────────────────────────────────────────────────────────
    async _loadEmployees() {
        try {
            // 1. Lấy thông tin nhân viên của user đang đăng nhập
            const myEmployee = await this.orm.searchRead(
                "hr.employee",
                [["user_id", "=", user.userId]],
                ["id", "name", "department_id"],
                { limit: 1 },
            );

            let myDepartmentId = null;
            if (myEmployee.length && myEmployee[0].department_id) {
                myDepartmentId = myEmployee[0].department_id[0];
            }

            // 2. Load danh sách phòng ban
            let deptDomain = [["active", "=", true]];
            if (this.state.isManager && !this.state.isHR && !this.state.isAdmin) {
                if (myDepartmentId) {
                    deptDomain.push(["id", "=", myDepartmentId]);
                } else {
                    deptDomain.push(["id", "=", 0]);
                }
            }

            const departments = await this.orm.searchRead(
                "hr.department",
                deptDomain,
                ["id", "name", "member_ids"],
                { order: "name asc" },
            );
            this.state.departments = departments;

            // 3. Load toàn bộ nhân viên (kèm theo department_id)
            let empDomain = [["active", "=", true]];
            if (this.state.isManager && !this.state.isHR && !this.state.isAdmin) {
                if (myDepartmentId) {
                    empDomain.push(["department_id", "=", myDepartmentId]);
                } else {
                    empDomain.push(["id", "=", 0]);
                }
            }

            const employees = await this.orm.searchRead(
                "hr.employee",
                empDomain,
                ["id", "name", "department_id"],
                { order: "name asc", limit: 500 }, // Tăng limit nếu công ty đông
            );
            this.state.employees = employees;

            if (departments.length > 0) {
                this.state.selectedDepartmentId = departments[0].id;
                const deptMembers = employees.filter(
                    (e) => e.department_id && e.department_id[0] === departments[0].id,
                );
                if (
                    myEmployee.length &&
                    deptMembers.find((e) => e.id === myEmployee[0].id)
                ) {
                    this.state.selectedEmployeeId = myEmployee[0].id;
                } else if (deptMembers.length > 0) {
                    this.state.selectedEmployeeId = deptMembers[0].id;
                } else if (employees.length > 0) {
                    this.state.selectedEmployeeId = employees[0].id;
                }
            } else {
                this.state.selectedDepartmentId = null;
                this.state.selectedEmployeeId = null;
            }

            // Nếu có passedEmployeeId, override selectedEmployeeId và selectedDepartmentId
            if (this.state.employee_id) {
                const targetEmp = employees.find(
                    (e) => e.id === this.state.employee_id,
                );
                if (targetEmp) {
                    this.state.selectedEmployeeId = targetEmp.id;
                    if (targetEmp.department_id) {
                        this.state.selectedDepartmentId = targetEmp.department_id[0];
                    }
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
                (emp) =>
                    emp.department_id &&
                    emp.department_id[0] === this.state.selectedDepartmentId,
            );
        } else {
            // Nếu chọn "Tất cả phòng ban"
            this.state.filteredEmployees = this.state.employees;
        }

        // Kiểm tra xem selectedEmployeeId hiện tại có nằm trong list vừa lọc không
        const empExists = this.state.filteredEmployees.find(
            (e) => e.id === this.state.selectedEmployeeId,
        );

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
                "id",
                "name",
                "period",
                "start_date",
                "end_date",
                "performance_score",
                "performance_level",
                "final_score",
                "final_level",
                "state",
                "employee_id",
            ];

            // Domain: filter by selected employee (manager) or by current user
            let domain;
            if (
                (this.state.isManager || this.state.isHR || this.state.isAdmin) &&
                this.state.selectedEmployeeId
            ) {
                domain = [["employee_id", "=", this.state.selectedEmployeeId]];
            } else if (this.state.employee_id) {
                // Được truyền thẳng employee_id từ context (ví dụ: mở từ form nhân viên)
                domain = [["employee_id", "=", this.state.employee_id]];
            } else {
                domain = [["employee_id.user_id", "=", user.userId]];
            }

            const evals = await this.orm.searchRead(
                "hr.performance.evaluation",
                domain,
                fields,
                { order: "start_date desc", limit: 500, context: { active_test: false } }, // Thêm dòng này để lấy cả record archived
            );

            this.state.evaluations = evals;

            if (evals.length > 0) {
                // Kiểm tra xem passedEvaluationId có khớp với evaluation nào trong danh sách không
                const targetEval = evals.find(e => e.id === this.state.passedEvaluationId);

                if (targetEval) {
                    this.state.selectedEvaluationId = targetEval.id;
                    // Reset lại để các lần user tự chọn nhân viên khác thì nó fallback về evals[0]
                    this.state.passedEvaluationId = false; 
                } else {
                    this.state.selectedEvaluationId = evals[0].id;
                }
                this.state.phase = "dashboard";
            } else {
                this.state.data = null;
                this.state.phase = "done";
            }
        } catch (e) {
            this.state.errorMsg = _t("Could not load evaluations.");
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
                [[this.state.selectedEvaluationId]],
            );
            this.state.data = data;
            this.state.phase = "done";

            console.log("data", data);

            // await Promise.resolve();
            // Ép trình duyệt đợi đến frame tiếp theo (đảm bảo thẻ <canvas> đã xuất hiện trên DOM)
            // await new Promise(resolve => requestAnimationFrame(resolve));

            // this._renderCharts();
        } catch (e) {
            this.state.errorMsg = _t("Could not load dashboard data.");
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
        this.state.selectedEvaluationId = null;
        this.state.data = null;
        await this._loadEvaluations();
        if (this.state.selectedEvaluationId) {
            await this._loadDashboard();
        }
    }

    async onSelectEmployee(ev) {
        const id = parseInt(ev.target.value, 10);
        if (!id || id === this.state.selectedEmployeeId) return;
        this.state.selectedEmployeeId = id;
        this.state.evaluations = [];
        this.state.selectedEvaluationId = null;
        this.state.data = null;
        await this._loadEvaluations();
        if (this.state.selectedEvaluationId) {
            await this._loadDashboard();
        }
    }

    async onSelectEval(ev) {
        const id = parseInt(ev.target.value, 10);
        if (!id || id === this.state.selectedEvaluationId) return;
        this.state.selectedEvaluationId = id;
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
        const color =
            level === "excellent"
                ? COLOR_BLUE
                : level === "pass"
                    ? COLOR_GREEN
                    : COLOR_RED;
        return "background: conic-gradient(" + color + " " + pct + "%, #e5e7eb 0)";
    }

    // get levelLabel() {
    //     return this.state.data ? this.state.data.performance_level : "";
    // }

    // get levelClass() {
    //     return "o_kpi_level_badge o_kpi_level_" + this.levelLabel;
    // }

    get levelLabel() {
        // Trả về thẳng Label đã được Python dịch
        return this.state.data ? this.state.data.performance_level_label : "";
    }

    // Nếu bạn có hàm set CSS dựa trên level, hãy giữ nguyên dùng key gốc:
    get levelClass() {
        const level = this.state.data ? this.state.data.performance_level : "";
        // Ví dụ: return level === 'fail' ? 'text-danger' : 'text-success';
        return "o_kpi_level_badge o_kpi_level_" + level;
    }

    get deptScoreText() {
        if (!this.state.data || !this.state.data.has_dept_evaluation) return "N/A";
        return (this.state.data.dept_kpi_score || 0).toFixed(1);
    }

    get individualWeightText() {
        const weight = this.state.data ? this.state.data.individual_weight : 1;
        return Math.round((weight || 0) * 100) + "%";
    }

    get deptWeightText() {
        const weight = this.state.data ? this.state.data.dept_weight : 0;
        return Math.round((weight || 0) * 100) + "%";
    }

    get deptStatusClass() {
        const level = this._levelFromScore(
            this.state.data ? this.state.data.dept_kpi_score : 0,
        );
        return "o_kpi_level_badge o_kpi_level_" + level;
    }

    get deptStatusLabel() {
        if (!this.state.data || !this.state.data.has_dept_evaluation) return "N/A";
        const level = this._levelFromScore(this.state.data.dept_kpi_score || 0);
        const labels = { excellent: "Excellent", pass: "Pass", fail: "Fail" };
        return labels[level];
    }

    get deptTooltip() {
        if (this.state.data?.has_dept_evaluation) {
            return _t("Department score participates in the final KPI formula.");
        }
        return _t(
            "No department evaluation is linked. The individual KPI receives 100% weight.",
        );
    }

    get formulaText() {
        return `${this.individualWeightText} Individual + ${this.deptWeightText} Department`;
    }

    _levelFromScore(score) {
        if (score >= 9) return "excellent";
        if (score >= 5) return "pass";
        return "fail";
    }

    // ── Final Score helpers (dùng cho breakdown section trong template) ────────
    get finalScoreText() {
        // Trả về final_score đã được làm tròn 2 chữ số thập phân
        return (this.state.data ? this.state.data.final_score : 0).toFixed(2);
    }

    get finalLevelClass() {
        // Class CSS tương ứng với final_level (excellent / pass / fail)
        const level = this.state.data ? this.state.data.final_level : "fail";
        return "o_kpi_level_badge o_kpi_level_" + level;
    }

    get finalLevelLabel() {
        if (this.state.data?.final_level_label) return this.state.data.final_level_label;
        const level = this.state.data ? this.state.data.final_level : "fail";
        const labels = { excellent: "Excellent", pass: "Pass", fail: "Fail" };
        return labels[level] || level;
    }

    // -------------------------------------------------------------------------
    // Bảng Quantitative - Xử lý Logic Status & Variance
    // -------------------------------------------------------------------------

    // 1. Format text cho cột Variance (Thêm dấu + cho số dương)
    formatVariance(row) {
        if (row.variance === 0) return "0%";
        return row.variance > 0 ? `+${row.variance}%` : `${row.variance}%`;
    }

    // 2. Màu sắc cho cột Variance
    varianceClass(row) {
        if (row.variance === 0) return "o_kpi_variance o_kpi_variance_good";

        // Xác định xem variance hiện tại là Tích cực (Good) hay Tiêu cực (Bad)
        const isGood =
            row.direction === "lower_better" ? row.variance < 0 : row.variance > 0;

        return isGood
            ? "o_kpi_variance o_kpi_variance_exceeded"
            : "o_kpi_variance o_kpi_variance_bad";
    }

    // 3. Chữ hiển thị cho cột Status
    statusText(row) {
        // Đúng Target (Variance = 0) -> Achieved
        if (row.variance === 0) return _t("Achieved");

        // Xác định Tích cực/Tiêu cực
        const isGood =
            row.direction === "lower_better" ? row.variance < 0 : row.variance > 0;

        // Tích cực -> Exceeded, Tiêu cực -> Not Met
        return isGood ? _t("Exceeded") : _t("Not Met");
    }

    // 4. Màu nền cho Badge Status
    statusClass(row) {
        // Đạt chính xác Target -> Dùng màu Xanh lá (Pass)
        if (row.variance === 0) return "o_kpi_status o_kpi_status_pass";

        const isGood =
            row.direction === "lower_better" ? row.variance < 0 : row.variance > 0;

        // Vượt mục tiêu -> Xanh dương đậm (Excellent)
        // Không đạt -> Đỏ (Fail)
        return isGood
            ? "o_kpi_status o_kpi_status_excellent"
            : "o_kpi_status o_kpi_status_fail";
    }

    periodLabel(period) {
        return PERIOD_LABELS[period] || period;
    }

    formatHour(h) {
        return formatHour(h);
    }

    evalOptionLabel(ev) {
        let periodLabel = "";

        // Kiểm tra nếu period là monthly và có start_date
        if (ev.period === "monthly" && ev.start_date) {
            // start_date có dạng "YYYY-MM-DD", tách chuỗi lấy phần tử thứ 2 (index 1)
            const monthString = ev.start_date.split("-")[1];

            // parseInt để bỏ số 0 ở đầu (ví dụ: "05" thành 5)
            const monthNumber = parseInt(monthString, 10);

            // Dùng _t() để có thể dịch từ "Month" sang "Tháng" trong file .po
            periodLabel = _t("Month ") + monthNumber;
        } else {
            // Fallback về logic cũ cho các period khác (yearly, quarterly...)
            periodLabel = PERIOD_LABELS[ev.period] || ev.period;
        }

        return (
            ev.name +
            " — " +
            periodLabel
        );
    }

    // ── Chart rendering ──────────────────────────────────────────────────────
    _renderCharts() {
        const Chart = window.Chart;
        const d = this.state.data;
        if (!Chart || !d) return;
        this._destroyCharts();

        // 1. Task Completion
        //        const taskEl = this.taskRef.el;
        //        if (taskEl && d.task_completion.labels.length) {
        //            this._charts.task = new Chart(taskEl, {
        //                type: "line",
        //                data: {
        //                    labels: d.task_completion.labels,
        //                    datasets: [
        //                        {
        //                            label: "On-time %",
        //                            data: d.task_completion.data,
        //                            borderColor: COLOR_BLUE,
        //                            backgroundColor: "rgba(59,130,246,0.15)",
        //                            fill: true, tension: 0.4, pointRadius: 5, spanGaps: true,
        //                        },
        //                        {
        //                            label: "Target",
        //                            data: Array(d.task_completion.labels.length).fill(d.task_completion.target),
        //                            borderColor: COLOR_GREEN, borderDash: [6, 4],
        //                            borderWidth: 1.5, pointRadius: 0, fill: false,
        //                        },
        //                    ],
        //                },
        //                options: {
        //                    responsive: true,
        //                    plugins: {
        //                        legend: { display: false },
        //                        tooltip: {
        //                            callbacks: {
        //                                label: (c) => c.dataset.label + ": " + (c.parsed.y != null ? c.parsed.y : "--") + "%",
        //                            },
        //                        },
        //                    },
        //                    scales: {
        //                        x: { ticks: { maxTicksLimit: 10, font: { size: 10 } }, grid: { display: false } },
        //                        y: { min: 0, max: 100, ticks: { callback: (v) => v + "%" }, grid: { color: "rgba(0,0,0,0.05)" } },
        //                    },
        //                },
        //            });
        //        }

        // 2. Punctuality Log
        const puncEl = this.puncRef.el;
        if (puncEl && d.punctuality_log.labels.length) {
            const expectedH = d.punctuality_log.expected_hour || 8;
            const yMin = Math.max(0, Math.floor(expectedH) - 1);
            const yMax = Math.ceil(expectedH) + 1.5;
            this._charts.punctuality = new Chart(puncEl, {
                type: "line",
                data: {
                    labels: d.punctuality_log.labels,
                    datasets: [
                        {
                            label: _t("Check-in"),
                            data: d.punctuality_log.data,
                            borderColor: COLOR_GREEN,
                            backgroundColor: "rgba(34,197,94,0.12)",
                            fill: true,
                            tension: 0.3,
                            pointRadius: 5,
                            spanGaps: true,
                        },
                        {
                            label: _t("Start time"),
                            data: Array(d.punctuality_log.labels.length).fill(expectedH),
                            borderColor: COLOR_RED,
                            borderDash: [5, 4],
                            borderWidth: 1.5,
                            pointRadius: 0,
                            fill: false,
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
                                    return (
                                        c.dataset.label + ": " + (v != null ? formatHour(v) : "--")
                                    );
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            ticks: { maxTicksLimit: 10, font: { size: 10 } },
                            grid: { display: false },
                        },
                        y: {
                            min: yMin,
                            max: yMax,
                            ticks: {
                                stepSize: 0.25,
                                callback: (v) => formatHour(v), // Tái sử dụng luôn hàm đã có
                            },
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
                    datasets: [
                        {
                            label: _t("Score"),
                            data: d.spider_web.scores,
                            backgroundColor: "rgba(99,102,241,0.25)",
                            borderColor: COLOR_INDIGO,
                            borderWidth: 2,
                            pointBackgroundColor: COLOR_INDIGO,
                            pointRadius: 4,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    // Cho phép tự do thay đổi chiều cao của Chart (không bị fix cứng tỷ lệ vuông)
                    maintainAspectRatio: false,

                    // 1. CHỐNG CẮT CHỮ: Chừa lề xung quanh chart (Tăng số này lên nếu chữ vẫn bị cắt)
                    layout: {
                        padding: 30,
                    },

                    plugins: { legend: { display: false } },
                    scales: {
                        r: {
                            min: 0,
                            max: 10,
                            ticks: { stepSize: 2, font: { size: 10 } },
                            pointLabels: {
                                font: { size: 11 },
                                // 2. TỰ ĐỘNG NGẮT DÒNG CHO NHÃN QUÁ DÀI
                                callback: function (label) {
                                    const maxLength = 15; // Ký tự tối đa trên 1 dòng (bạn có thể tùy chỉnh)
                                    if (typeof label === "string" && label.length > maxLength) {
                                        // Cắt theo dấu cách để không làm đứt đôi 1 từ
                                        const words = label.split(" ");
                                        let lines = [];
                                        let currentLine = "";

                                        words.forEach((word) => {
                                            if ((currentLine + word).length > maxLength) {
                                                if (currentLine) lines.push(currentLine.trim());
                                                currentLine = word + " ";
                                            } else {
                                                currentLine += word + " ";
                                            }
                                        });
                                        if (currentLine) lines.push(currentLine.trim());

                                        return lines; // Trả về mảng -> Chart.js sẽ hiển thị nhiều dòng
                                    }
                                    return label;
                                },
                            },
                            grid: { color: "rgba(0,0,0,0.07)" },
                        },
                    },
                },
            });
        }

        // 4. Attendance Overview (Doughnut)
        const attendanceEl = this.attendanceRef.el;
        if (
            attendanceEl &&
            d.attendance_full &&
            d.attendance_full.summary.expected_work_days > 0
        ) {
            const worked = d.attendance_full.summary.worked_days;
            const expected = d.attendance_full.summary.expected_work_days;
            const absent = expected - worked;

            this._charts.attendance = new Chart(attendanceEl, {
                type: "doughnut",
                data: {
                    labels: [_t("Days Present"), _t("Days Absent")],
                    datasets: [
                        {
                            data: [worked, absent],
                            backgroundColor: ["#3b82f6", "#e2e8f0"], // Matching legend color
                            borderWidth: 0,
                            hoverOffset: 4,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "75%", // makes it a thin ring
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (c) => c.label + ": " + c.parsed + _t(" days"),
                            },
                        },
                    },
                },
            });
        }

        // 5. Done Tasks by Day
        const doneTasksEl = this.doneTasksRef.el;
        if (
            doneTasksEl &&
            d.done_tasks_by_day &&
            d.done_tasks_by_day.labels.length
        ) {
            const dtd = d.done_tasks_by_day;
            this._charts.doneTasks = new Chart(doneTasksEl, {
                type: "line",
                data: {
                    labels: dtd.labels,
                    datasets: [
                        {
                            label: _t("Done Tasks"),
                            data: dtd.done_by_day,
                            borderColor: COLOR_GREEN,
                            backgroundColor: "rgba(34,197,94,0.12)",
                            fill: true,
                            tension: 0.4,
                            pointRadius: 4,
                            pointBackgroundColor: COLOR_GREEN,
                            spanGaps: false,
                        },
                        {
                            label: _t("Total Tasks (target)"),
                            data: Array(dtd.labels.length).fill(dtd.total),
                            borderColor: COLOR_RED,
                            borderDash: [6, 4],
                            borderWidth: 1.5,
                            pointRadius: 0,
                            fill: false,
                            tension: 0,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: true, position: "top" },
                        tooltip: {
                            callbacks: {
                                label: (c) => {
                                    if (c.datasetIndex === 1) {
                                        return _t("Total in period: ") + dtd.total + _t(" tasks");
                                    }
                                    return _t("Done (Total): ") + c.parsed.y + _t(" tasks");
                                },
                            },
                        },
                    },
                    scales: {
                        x: {
                            ticks: { maxTicksLimit: 10, font: { size: 10 } },
                            grid: { display: false },
                        },
                        y: {
                            beginAtZero: true,
                            ticks: {
                                stepSize: 1,
                                font: { size: 10 },
                                callback: (v) => (Number.isInteger(v) ? v : ""),
                            },
                            grid: { color: "rgba(0,0,0,0.05)" },
                            title: {
                                display: true,
                                text: _t("Tasks"),
                                font: { size: 11 },
                            },
                        },
                    },
                },
            });
        }
    }

    _destroyCharts() {
        for (const k of Object.keys(this._charts)) {
            try {
                this._charts[k].destroy();
            } catch (_) { }
        }
        this._charts = {};
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Register as client action
// ─────────────────────────────────────────────────────────────────────────────
registry.category("actions").add("kpi_individual_dashboard", KpiDashboard);
