from odoo import models, fields, api, _
from odoo.exceptions import UserError
import re
import logging

_logger = logging.getLogger(__name__)


class HrEmployeeInherit(models.Model):
    _inherit = 'hr.employee'

    employee_code = fields.Char(
        string='Employee Code',
        copy=False,
        index=True,
        readonly=True,
        help="Unique employee code (e.g., P0001, TCIP0012, BC0005)"
    )

    engagement_location = fields.Selection(
        [
            ('onsite', 'Onsite'),
            ('offshore', 'Offshore'),
            ('near_shore', 'Nearshore'),
        ],
        string='Engagement Location'
    )

    payroll_location = fields.Selection([
        ('dubai_onsite', 'Dubai- Onsite'),
        ('dubai_offshore', 'Dubai-Offshore'),
        ('tcip_india', 'TCIP India'),
    ], string='Payroll')

    employment_type = fields.Selection([
        ('permanent', 'Permanent'),
        ('temporary', 'Temporary'),
        ('bootcamp', 'Bootcamp'),
        ('seconded', 'Seconded'),
        ('freelancer', 'Freelancer'),
    ], string='Employment Type')

    @api.model
    def create(self, vals):
        """Sync employee_code to emp_code on create"""
        res = super(HrEmployeeInherit, self).create(vals)
        if res.employee_code:
            res.emp_code = res.employee_code
        return res

    def write(self, vals):
        """Sync employee_code to emp_code on write"""
        res = super(HrEmployeeInherit, self).write(vals)
        if 'employee_code' in vals:
            for record in self:
                if record.employee_code:
                    record.sudo().write({'emp_code': record.employee_code})
        return res

    def action_open_code_generation_wizard(self):
        """Open wizard to generate employee code"""
        self.ensure_one()

        if self.employee_code:
            raise UserError(_(
                'Employee Code already exists: %s\n'
                'Cannot generate a new code for this employee.'
            ) % self.employee_code)

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

    def action_generate_employee_code(self):
        """
        BACKWARD COMPATIBILITY METHOD
        This redirects old button calls to new wizard
        Keep this until azure_ad_integration module is updated
        """
        _logger.warning(
            "action_generate_employee_code is deprecated. "
            "Use action_open_code_generation_wizard instead"
        )
        return self.action_open_code_generation_wizard()

    def action_bulk_generate_employee_codes(self):
        """Generate employee codes for all employees without codes"""
        employees_without_code = self.search([
            '|',
            ('employee_code', '=', False),
            ('employee_code', '=', '')
        ])

        if not employees_without_code:
            raise UserError(_('All employees already have employee codes!'))

        incomplete_employees = employees_without_code.filtered(
            lambda e: not e.engagement_location or not e.payroll_location or not e.employment_type
        )

        if incomplete_employees:
            raise UserError(_(
                'Cannot generate codes in bulk. The following employees are missing classification fields:\n\n%s\n\n'
                'Please complete their Engagement Location, Payroll, and Employment Type fields first.'
            ) % '\n'.join(incomplete_employees.mapped('name')))

        generated_count = 0

        for employee in employees_without_code:
            new_code = employee._generate_next_employee_code()
            employee.write({'employee_code': new_code})
            generated_count += 1
            _logger.info(f"Bulk Generated: {new_code} for {employee.name}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Generated %d employee codes successfully!') % generated_count,
                'type': 'success',
                'sticky': True,
            }
        }

    def _generate_next_employee_code(self):
        """Generate employee code based on classification fields"""
        prefix = self._get_employee_code_prefix()

        if not prefix:
            prefix = 'EMP'

        all_employees = self.search([
            ('employee_code', '!=', False),
            ('employee_code', '=like', f'{prefix}%')
        ])

        existing_codes = [emp.employee_code for emp in all_employees if emp.employee_code]

        max_number = 0
        for code in existing_codes:
            match = re.match(rf'^{re.escape(prefix)}(\d+)$', code)
            if match:
                number = int(match.group(1))
                max_number = max(max_number, number)

        next_number = max_number + 1
        new_code = f"{prefix}{next_number:04d}"

        _logger.info(f"Generated code: {new_code} (Prefix: {prefix}, Next: {next_number})")

        return new_code

    def _get_employee_code_prefix(self):
        """Determine prefix based on Engagement Location, Payroll, and Employment Type"""
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
                return 'OP'

        if engagement in ['onsite', 'near_shore'] and payroll == 'dubai_onsite' and emp_type == 'permanent':
            return 'P'

        if engagement in ['onsite', 'near_shore'] and payroll == 'dubai_onsite' and emp_type == 'temporary':
            return 'T'

        _logger.warning(f"No prefix match for: {engagement}, {payroll}, {emp_type}")
        return 'EMP'

    @api.constrains('employee_code')
    def _check_employee_code_unique(self):
        """Ensure employee code is unique"""
        for employee in self:
            if employee.employee_code:
                duplicate = self.search([
                    ('employee_code', '=', employee.employee_code),
                    ('id', '!=', employee.id)
                ], limit=1)
                if duplicate:
                    raise UserError(_(
                        'Employee Code "%s" already exists for employee: %s'
                    ) % (employee.employee_code, duplicate.name))