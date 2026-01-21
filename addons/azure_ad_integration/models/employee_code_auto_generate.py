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
        help="Unique employee code (e.g., EMP001, B0012, TC221)"
    )
    engagement_location = fields.Selection([
        ('onsite_nearshore', 'Onsite / Nearshore'),
        ('offshore', 'Offshore'),
    ], string='Engagement Location')

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

    def action_generate_employee_code(self):
        """Generate employee code with sequence"""
        for employee in self:
            if employee.employee_code:
                raise UserError(_(
                    'Employee Code already exists: %s\n'
                    'Cannot generate a new code for employee: %s'
                ) % (employee.employee_code, employee.name))

            # Generate new code
            new_code = self._generate_next_employee_code()
            employee.write({'employee_code': new_code})

            _logger.info(f"Generated Employee Code: {new_code} for {employee.name} (ID: {employee.id})")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Employee Code "%s" generated successfully!') % new_code,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_bulk_generate_employee_codes(self):
        """Generate employee codes for all employees without codes"""
        employees_without_code = self.search([
            '|',
            ('employee_code', '=', False),
            ('employee_code', '=', '')
        ])

        if not employees_without_code:
            raise UserError(_('All employees already have employee codes!'))

        generated_count = 0

        for employee in employees_without_code:
            new_code = self._generate_next_employee_code()
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
        """
        Generate employee code based on:
        - Engagement Location
        - Payroll
        - Employment Type
        """

        # Determine prefix based on the 3 fields
        prefix = self._get_employee_code_prefix()

        if not prefix:
            # Fallback to default if fields not set
            prefix = 'EMP'

        # Get all existing codes with this prefix
        all_employees = self.search([
            ('employee_code', '!=', False),
            ('employee_code', '=like', f'{prefix}%')
        ])

        existing_codes = [emp.employee_code for emp in all_employees if emp.employee_code]

        # Find the highest number with this prefix
        max_number = 0
        for code in existing_codes:
            match = re.match(rf'^{re.escape(prefix)}(\d+)$', code)
            if match:
                number = int(match.group(1))
                max_number = max(max_number, number)

        # Generate next code
        next_number = max_number + 1
        new_code = f"{prefix}{next_number:04d}"  # 4 digits with leading zeros

        _logger.info(f"Generated code: {new_code} (Prefix: {prefix}, Next: {next_number})")

        return new_code

    def _get_employee_code_prefix(self):
        """
        Determine prefix based on Engagement Location, Payroll, and Employment Type

        Logic from table:
        - P: Onsite/Nearshore + Dubai-Onsite + Permanent
        - T: Onsite/Nearshore + Dubai-Onsite + Temporary
        - OP: Offshore + Dubai-Offshore + Permanent/Temporary
        - TCIP: Offshore + TCIP India + Permanent
        - BC: Onsite + Dubai-Onsite + Bootcamp
        - BCO: Offshore + Dubai-Offshore + Bootcamp
        - BCI: Offshore + TCIP India + Bootcamp
        - PT: Any + Any + Seconded (Manual entry)
        - TFL: Onsite/Offshore/Nearshore + Dubai-Onsite/Dubai-Offshore/TCIP + Freelancer
        """

        engagement = self.engagement_location
        payroll = self.payroll_location
        emp_type = self.employment_type

        _logger.info(f"Determining prefix for: Engagement={engagement}, Payroll={payroll}, Type={emp_type}")

        # Seconded - Manual entry (PT prefix)
        if emp_type == 'seconded':
            return 'PT'

        # Freelancer - TFL prefix
        if emp_type == 'freelancer':
            return 'TFL'

        # Bootcamp
        if emp_type == 'bootcamp':
            if engagement == 'onsite_nearshore' and payroll == 'dubai_onsite':
                return 'BC'
            elif engagement == 'offshore' and payroll == 'dubai_offshore':
                return 'BCO'
            elif engagement == 'offshore' and payroll == 'tcip_india':
                return 'BCI'

        # TCIP India Permanent
        if engagement == 'offshore' and payroll == 'tcip_india' and emp_type == 'permanent':
            return 'TCIP'

        # Offshore Permanent/Temporary
        if engagement == 'offshore' and payroll == 'dubai_offshore':
            if emp_type in ['permanent', 'temporary']:
                return 'OP'

        # Onsite/Nearshore Permanent
        if engagement == 'onsite_nearshore' and payroll == 'dubai_onsite' and emp_type == 'permanent':
            return 'P'

        # Onsite/Nearshore Temporary
        if engagement == 'onsite_nearshore' and payroll == 'dubai_onsite' and emp_type == 'temporary':
            return 'T'

        # Default fallback
        _logger.warning(f"No prefix match found for combination: {engagement}, {payroll}, {emp_type}")
        return 'EMP'

    def _analyze_code_patterns(self, codes):
        """Analyze existing employee codes to detect patterns"""
        patterns = {}

        for code in codes:
            match = re.match(r'^([A-Za-z]+)(\d+)$', code)

            if match:
                prefix, number_str = match.groups()
                number = int(number_str)
                digits = len(number_str)

                if prefix not in patterns:
                    patterns[prefix] = {
                        'count': 0,
                        'max_number': 0,
                        'digits': digits
                    }

                patterns[prefix]['count'] += 1
                patterns[prefix]['max_number'] = max(patterns[prefix]['max_number'], number)
                patterns[prefix]['digits'] = min(patterns[prefix]['digits'], digits)

        return patterns

    @api.model
    def create(self, vals_list):
        """
        Odoo 19 safe create override:
        - Handles dict and list
        - Supports bulk create
        - Respects auto_generate_code context
        """

        if isinstance(vals_list, dict):
            vals_list = [vals_list]

        for vals in vals_list:
            if not vals.get('employee_code'):
                if self.env.context.get('auto_generate_code', True):
                    vals['employee_code'] = self._generate_next_employee_code()

        return super(HrEmployeeInherit, self).create(vals_list)

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