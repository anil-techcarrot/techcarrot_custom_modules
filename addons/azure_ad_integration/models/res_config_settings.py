# File: models/res_config_settings.py

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    employee_code_prefix = fields.Char(
        string='Employee Code Prefix',
        default='EMP',
        config_parameter='hr.employee_code_prefix',
        help='Default prefix for employee codes (e.g., EMP, B, TC)'
    )

    employee_code_digits = fields.Integer(
        string='Employee Code Digits',
        default=3,
        config_parameter='hr.employee_code_digits',
        help='Number of digits in the sequential number (e.g., 3 = 001, 4 = 0001)'
    )