from odoo import models, fields, api, _
from odoo.exceptions import UserError
import re
import logging

_logger = logging.getLogger(__name__)


class HrEmployeeInherit(models.Model):
    _inherit = 'hr.employee'

    # ---------------------------------
    # Employee Code Fields (NEW)
    # ---------------------------------

    emp_code = fields.Char(
        string='Emp Code',
        copy=False,
        index=True,
        readonly=True,
        store=True,
        help="Unique employee code (e.g., P0001, TCIP0012, BC0005)"
    )

    employee_code = fields.Char(
        string='Employee Code',
        copy=False,
        index=True,
        readonly=True,
        store=True,
        help="Unique employee code (e.g., P0001, TCIP0012, BC0005)"
    )

    line_manager_id = fields.Many2one(
        'hr.employee',
        string='Line Manager',
        copy=False
    )

    # ------------------------------------------------
    # Wizard Action
    # ------------------------------------------------

    def action_open_code_generation_wizard(self):
        self.ensure_one()

        if self.emp_code:
            raise UserError(_(
                'Employee Code already exists: %s\n'
                'Cannot generate a new code for this employee.'
            ) % self.emp_code)

        return {
            'name': _('Generate Employee Code'),
            'type': 'ir.actions.act_window',
            'res_model': 'employee.code.generation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_employee_id': self.id,
                'default_engagement_location': self.engagement_location,
                'default_payroll_location': self.payroll_location,
                'default_employment_type': self.employment_type,
            }
        }

    # ------------------------------------------------
    # Code Generation Logic
    # ------------------------------------------------

    def _generate_next_employee_code(self):

        prefix = self._get_employee_code_prefix() or 'EMP'

        employees = self.search([
            ('emp_code', '!=', False),
            ('emp_code', '=like', f'{prefix}%')
        ])

        max_number = 0
        for code in employees.mapped('emp_code'):
            match = re.match(rf'^{re.escape(prefix)}(\d+)$', code)
            if match:
                max_number = max(max_number, int(match.group(1)))

        new_code = f"{prefix}{max_number + 1}"

        _logger.info("Generated Employee Code: %s", new_code)

        return new_code

    def _get_employee_code_prefix(self):

        engagement = self.engagement_location
        payroll = self.payroll_location
        emp_type = self.employment_type

        if emp_type == 'seconded':
            return 'PT'

        if emp_type == 'freelancer':
            return 'TFL'

        if emp_type == 'bootcamp':
            if engagement in ['onsite', 'near_shore'] and payroll == 'dubai_onsite':
                return 'BC'
            elif engagement == 'offshore' and payroll == 'dubai_offshore':
                return 'BCO'
            elif engagement == 'offshore' and payroll == 'tcip_india':
                return 'BCI'

        if engagement == 'offshore' and payroll == 'tcip_india' and emp_type == 'permanent':
            return 'TCIP'

        if engagement == 'offshore' and payroll == 'dubai_offshore':
            if emp_type in ['permanent', 'temporary']:
                return 'T'

        if engagement in ['onsite', 'near_shore'] and payroll == 'dubai_onsite':
            if emp_type == 'permanent':
                return 'P'
            elif emp_type == 'temporary':
                return 'T'

        return 'EMP'

    # ------------------------------------------------
    # Unique Validation
    # ------------------------------------------------

    @api.constrains('emp_code')
    def _check_employee_code_unique(self):
        for emp in self:
            if emp.emp_code:
                duplicate = self.search([
                    ('emp_code', '=', emp.emp_code),
                    ('id', '!=', emp.id)
                ], limit=1)

                if duplicate:
                    raise UserError(_(
                        'Employee Code "%s" already exists for employee: %s'
                    ) % (emp.emp_code, duplicate.name))
