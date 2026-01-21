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
        """Generate the next sequential employee code"""

        # Default values (hardcoded for now, can be made configurable later)
        default_prefix = 'EMP'
        default_digits = 3

        # Get all existing employee codes
        all_employees = self.search([('employee_code', '!=', False)])
        existing_codes = [emp.employee_code for emp in all_employees if emp.employee_code]

        if not existing_codes:
            # No codes exist, start fresh
            return f"{default_prefix}{1:0{default_digits}d}"

        # Analyze existing codes to find patterns
        code_patterns = self._analyze_code_patterns(existing_codes)

        if code_patterns:
            # Use the most common pattern
            most_common_prefix = max(code_patterns, key=lambda x: code_patterns[x]['count'])
            pattern_info = code_patterns[most_common_prefix]

            next_number = pattern_info['max_number'] + 1
            digits = pattern_info['digits']

            new_code = f"{most_common_prefix}{next_number:0{digits}d}"
            _logger.info(f"Pattern detected: {most_common_prefix} (used {pattern_info['count']} times)")
        else:
            # Fallback: use default prefix
            new_code = f"{default_prefix}{1:0{default_digits}d}"

        # Ensure uniqueness
        counter = 1
        original_code = new_code
        while self.search([('employee_code', '=', new_code)], limit=1):
            match = re.match(r'^([A-Za-z]+)(\d+)$', original_code)
            if match:
                prefix, number = match.groups()
                digits = len(number)
                next_num = int(number) + counter
                new_code = f"{prefix}{next_num:0{digits}d}"
                counter += 1
            else:
                new_code = f"{original_code}_{counter}"
                counter += 1

        return new_code

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