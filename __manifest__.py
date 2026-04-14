{
    'name': 'ADEC SOL HR Performance Evaluator',
    'version': '18.0',
    'category': 'Human Resources',
    'author': 'Amare Tilaye',
    'website': 'https://www.amaretilaye.netlify.app',
    'license': 'LGPL-3',
    'images': ['static/description/icon.png'],
    'summary': 'Quản lý việc đánh giá hiệu suất làm việc của nhân viên bằng cách sử dụng các chỉ số KPI.',
    'depends': ['hr', 'base', 'mail', 'contacts', 'project', 'hr_attendance', 'hr_holidays', 'project_task_done_date'],
    'description': """

Mô-đun này được thiết kế để tối ưu hóa quy trình đánh giá và báo cáo hiệu suất, cung cấp cho các nhóm nhân sự những công cụ mạnh mẽ để quản lý và theo dõi hiệu suất của nhân viên.

    """,

    'data': [
        'data/data.xml',
        'data/kpi.xml',
        'data/email_template_evaluation_alert.xml',
        'data/ir_config_parameter_data.xml',
        'data/kpi_template_data.xml',

        'security/security.xml',
        'security/ir.model.access.csv',

        'views/kpi_view.xml',
        'views/performance_evaluation.xml',
        'views/hr_score.xml',
        'views/evaluation_alert_views.xml',
        'views/performance_evaluation_report.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'custom_adecsol_hr_performance_evaluator/static/src/scss/performance_badges.scss',
            'custom_adecsol_hr_performance_evaluator/static/src/scss/performance_evaluation.scss',
            'custom_adecsol_hr_performance_evaluator/static/src/js/kpi_one2many.js',
            'custom_adecsol_hr_performance_evaluator/static/src/js/evaluation_one2many.js',
            'custom_adecsol_hr_performance_evaluator/static/src/js/priority_with_onchange.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
