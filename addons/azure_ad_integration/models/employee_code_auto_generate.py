from odoo import models, fields, api, _
from odoo.exceptions import UserError
import re
import logging

_logger = logging.getLogger(__name__)


class HrEmployeeInherit(models.Model):
    _inherit = 'hr.employee'

    engagement_location = fields.Char('Engagement Location', copy=False)



    @api.model
    def create(self, vals):
        """Pass through - no manipulation"""
        res = super(HrEmployeeInherit, self).create(vals)
        return res

    def write(self, vals):
        """Pass through - no manipulation"""
        res = super(HrEmployeeInherit, self).write(vals)
        return res

    def action_open_code_generation_wizard(self):
        """Open wizard to generate employee code"""
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
            }
        }

    def _generate_next_employee_code(self):
        """Generate employee code based on classification fields"""
        prefix = self._get_employee_code_prefix()

        if not prefix:
            prefix = 'EMP'

        all_employees = self.search([
            ('emp_code', '!=', False),
            ('emp_code', '=like', f'{prefix}%')
        ])

        existing_codes = [emp.emp_code for emp in all_employees if emp.emp_code]

        max_number = 0
        for code in existing_codes:
            match = re.match(rf'^{re.escape(prefix)}(\d+)$', code)
            if match:
                number = int(match.group(1))
                max_number = max(max_number, number)

        next_number = max_number + 1
        new_code = f"{prefix}{next_number}"

        _logger.info(f"Generated code: {new_code} (Prefix: {prefix}, Next: {next_number})")

        return new_code

    def _normalize_for_comparison(self, value):
        """Normalize string for comparison in code generation"""
        if not value:
            return ''
        return str(value).lower().replace('-', '').replace('_', '').replace(' ', '').strip()

    def _get_employee_code_prefix(self):
        """Determine prefix based on Engagement Location, Payroll, and Employment Type"""
        engagement_norm = self._normalize_for_comparison(self.engagement_location)
        payroll_norm = self._normalize_for_comparison(self.payroll_location)
        emp_type_norm = self._normalize_for_comparison(self.employment_type)

        _logger.info(f"Prefix calc: eng='{engagement_norm}', pay='{payroll_norm}', type='{emp_type_norm}'")

        if emp_type_norm == 'seconded':
            return 'PT'

        if emp_type_norm == 'freelancer':
            return 'TFL'

        if emp_type_norm == 'bootcamp':
            if engagement_norm in ['onsite', 'nearshore'] and 'dubaionsite' in payroll_norm:
                return 'BC'
            elif engagement_norm == 'offshore' and 'dubaioffshore' in payroll_norm:
                return 'BCO'
            elif engagement_norm == 'offshore' and ('tcip' in payroll_norm or 'india' in payroll_norm):
                return 'BCI'

        if engagement_norm == 'offshore' and ('tcip' in payroll_norm or 'india' in payroll_norm) and emp_type_norm == 'permanent':
            return 'TCIP'

        if engagement_norm == 'offshore' and 'dubaioffshore' in payroll_norm:
            if emp_type_norm in ['permanent', 'temporary']:
                return 'T'

        if engagement_norm in ['onsite', 'nearshore'] and 'dubaionsite' in payroll_norm and emp_type_norm == 'permanent':
            return 'P'

        if engagement_norm in ['onsite', 'nearshore'] and 'dubaionsite' in payroll_norm and emp_type_norm == 'temporary':
            return 'T'

        _logger.warning(f"No prefix match for: {engagement_norm}, {payroll_norm}, {emp_type_norm}")
        return 'EMP'

    @api.constrains('emp_code')
    def _check_employee_code_unique(self):
        """Ensure employee code is unique"""
        for employee in self:
            if employee.emp_code:
                duplicate = self.search([
                    ('emp_code', '=', employee.emp_code),
                    ('id', '!=', employee.id)
                ], limit=1)
                if duplicate:
                    raise UserError(_(
                        'Employee Code "%s" already exists for employee: %s'
                    ) % (employee.emp_code, duplicate.name))