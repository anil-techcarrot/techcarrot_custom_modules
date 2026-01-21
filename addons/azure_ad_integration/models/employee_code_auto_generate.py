# File: models/hr_employee_inherit.py

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
        generated_codes = []

        for employee in employees_without_code:
            new_code = self._generate_next_employee_code()
            employee.write({'employee_code': new_code})
            generated_count += 1
            generated_codes.append(f"{employee.name}: {new_code}")
            _logger.info(f"Bulk Generated: {new_code} for {employee.name}")

        # Show summary of generated codes
        message = _('Generated %d employee codes:\n\n%s') % (
            generated_count,
            '\n'.join(generated_codes[:10])  # Show first 10
        )
        if generated_count > 10:
            message += _('\n... and %d more') % (generated_count - 10)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': message,
                'type': 'success',
                'sticky': True,
            }
        }

    def _generate_next_employee_code(self):
        """
        Generate the next sequential employee code
        Intelligently handles various formats:
        - EMP001, EMP002 -> EMP003
        - B0012, B0045 -> B0046
        - TC221, TC222 -> TC223
        - Mixed formats -> Uses most common prefix or defaults to EMP
        """

        # Get configuration for default prefix (you can make this configurable)
        IrConfigParam = self.env['ir.config_parameter'].sudo()
        default_prefix = IrConfigParam.get_param('hr.employee_code_prefix', 'EMP')
        default_digits = int(IrConfigParam.get_param('hr.employee_code_digits', '3'))

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
            _logger.info(f"Next code: {new_code}")
        else:
            # Fallback: use default prefix
            new_code = f"{default_prefix}{1:0{default_digits}d}"
            _logger.warning(f"No pattern detected, using default: {new_code}")

        # Ensure uniqueness
        counter = 1
        original_code = new_code
        while self.search([('employee_code', '=', new_code)], limit=1):
            # Extract prefix and number
            match = re.match(r'^([A-Za-z]+)(\d+)$', original_code)
            if match:
                prefix, number = match.groups()
                digits = len(number)
                next_num = int(number) + counter
                new_code = f"{prefix}{next_num:0{digits}d}"
                counter += 1
            else:
                # If format is weird, just append counter
                new_code = f"{original_code}_{counter}"
                counter += 1

        return new_code

    def _analyze_code_patterns(self, codes):
        """
        Analyze existing employee codes to detect patterns
        Returns dict: {prefix: {'count': X, 'max_number': Y, 'digits': Z}}

        Examples:
        - EMP001, EMP002, EMP015 -> {'EMP': {'count': 3, 'max_number': 15, 'digits': 3}}
        - B0012, B0045 -> {'B': {'count': 2, 'max_number': 45, 'digits': 4}}
        - TC221, TC222 -> {'TC': {'count': 2, 'max_number': 222, 'digits': 3}}
        """
        patterns = {}

        for code in codes:
            # Match pattern: letters followed by digits (e.g., EMP001, B0012, TC221)
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
                # Use minimum digits found (to handle B012 and B0012 consistently)
                patterns[prefix]['digits'] = min(patterns[prefix]['digits'], digits)
            else:
                _logger.warning(f"Code format not recognized: {code}")

        return patterns

    @api.model
    def create(self, vals):
        """Auto-generate employee code on creation if not provided"""
        # Only auto-generate if employee_code is not provided AND not coming from API
        # (API should set its own codes if needed)
        if not vals.get('employee_code'):
            # Check if this is being called from UI (has context) vs API
            if self.env.context.get('auto_generate_code', True):
                vals['employee_code'] = self._generate_next_employee_code()
        return super(HrEmployeeInherit, self).create(vals)

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
                        'Employee Code "%s" already exists for employee: %s\n'
                        'Please use a different code.'
                    ) % (employee.employee_code, duplicate.name))