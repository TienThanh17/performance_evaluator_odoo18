{
    'name': 'ADEC SOL HR Performance Evaluator',
    'version': '18.0',
    'category': 'Human Resources',
    'author': 'ADEC SOL',
    # 'website': 'https://www.adecsol.com',
    'license': 'LGPL-3',
    'images': ['static/description/icon.png'],
    'summary': 'Quản lý việc đánh giá hiệu suất làm việc của nhân viên bằng cách sử dụng các chỉ số KPI.',
    'depends': ['hr', 'base', 'mail', 'contacts', 'project', 'hr_attendance', 'hr_holidays', 'project_task_done_date'],
    'description': """

Mô-đun này được thiết kế để tối ưu hóa quy trình đánh giá và báo cáo hiệu suất, cung cấp cho các nhóm nhân sự những công cụ mạnh mẽ để quản lý và theo dõi hiệu suất của nhân viên.

    """,

    'data': [
        # ============================== SECURITY =============================
        'security/security.xml',
        'security/ir.model.access.csv',

        # ============================== DATA =============================
        'data/ir_config_parameter_data.xml',
        'data/ir_cron_data.xml',
        'data/email_template_evaluation_alert.xml',
        'data/kpi_sequence.xml',
        'data/kpi_IT_employee_data.xml',
        'data/kpi_IT_department_data.xml',

        # ============================== VIEWS =============================
        'views/hr_department_kpi_generate_wizard_views.xml',
        'views/res_config_settings_views.xml',
        'views/kpi_view.xml',
        'views/hr_department_kpi_views.xml',
        'views/hr_department_performance_views.xml',
        'views/performance_evaluation.xml',
        'views/performance_report_views.xml',
        'views/hr_score.xml',
        'views/kpi_generate_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'custom_adecsol_hr_performance_evaluator/static/src/scss/performance_badges.scss',
            'custom_adecsol_hr_performance_evaluator/static/src/scss/performance_evaluation.scss',
            'custom_adecsol_hr_performance_evaluator/static/src/scss/performance_dashboard.scss',
            'custom_adecsol_hr_performance_evaluator/static/src/js/kpi_one2many.js',
            'custom_adecsol_hr_performance_evaluator/static/src/js/evaluation_one2many.js',
            'custom_adecsol_hr_performance_evaluator/static/src/js/priority_with_onchange.js',
            'custom_adecsol_hr_performance_evaluator/static/src/js/performance_dashboard_form.js',
            'custom_adecsol_hr_performance_evaluator/static/src/js/kpi_description_custom_widget.js',
            'custom_adecsol_hr_performance_evaluator/static/src/xml/performance_dashboard_templates.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
