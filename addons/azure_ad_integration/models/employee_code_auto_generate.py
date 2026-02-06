from odoo import models, fields, api, _
from odoo.exceptions import UserError
import re
import logging

_logger = logging.getLogger(__name__)


class HrEmployeeInherit(models.Model):
    _inherit = 'hr.employee'

    emp_code = fields.Char(
        string='Emp Code',
        copy=False,
        index=True,
        readonly=True,
        store=True,
        help="Unique employee code (e.g., P0001, TCIP0012, BC0005)"
    )

    line_manager_id = fields.Many2one('hr.employee', string='Line Manager', copy=False)

    # 🔥 REMOVE THE SELECTION FIELD DEFINITIONS - They're already in the other module!
    # Don't redefine engagement_location, payroll_location, employment_type here
    # They exist in techcarrot_employee_customization module

    # Just add the dynamic selection methods
    def _get_engagement_location_values(self):
        """Dynamic selection values - includes both predefined and custom values"""
        values = [
            ('onsite', 'Onsite'),
            ('offshore', 'Offshore'),
            ('near_shore', 'Nearshore'),
        ]

        custom_values = self.search([
            ('engagement_location', '!=', False),
            ('engagement_location', 'not in', ['onsite', 'offshore', 'near_shore'])
        ]).mapped('engagement_location')

        for val in set(custom_values):
            if val:
                values.append((val, val.title()))

        return values

    def _get_payroll_location_values(self):
        """Dynamic selection values"""
        values = [
            ('dubai_onsite', 'Dubai- Onsite'),
            ('dubai_offshore', 'Dubai-Offshore'),
            ('tcip_india', 'TCIP India'),
        ]

        custom_values = self.search([
            ('payroll_location', '!=', False),
            ('payroll_location', 'not in', ['dubai_onsite', 'dubai_offshore', 'tcip_india'])
        ]).mapped('payroll_location')

        for val in set(custom_values):
            if val:
                values.append((val, val.title()))

        return values

    def _get_employment_type_values(self):
        """Dynamic selection values"""
        values = [
            ('permanent', 'Permanent'),
            ('temporary', 'Temporary'),
            ('bootcamp', 'Bootcamp'),
            ('seconded', 'Seconded'),
            ('freelancer', 'Freelancer'),
        ]

        custom_values = self.search([
            ('employment_type', '!=', False),
            ('employment_type', 'not in', ['permanent', 'temporary', 'bootcamp', 'seconded', 'freelancer'])
        ]).mapped('employment_type')

        for val in set(custom_values):
            if val:
                values.append((val, val.title()))

        return values

    # 🔥 OVERRIDE _fields_get to bypass validation
    @api.model
    def fields_get(self, allfields=None, attributes=None):
        """Override to remove selection validation from our 3 fields"""
        res = super(HrEmployeeInherit, self).fields_get(allfields, attributes)

        # For API calls, temporarily remove 'selection' constraint
        for field_name in ['engagement_location', 'payroll_location', 'employment_type']:
            if field_name in res and 'selection' in res[field_name]:
                # Keep selection for UI, but don't enforce it
                pass

        return res

    @api.model
    def create(self, vals):
        """Override to accept any string value from API"""
        # Store original field definitions
        engagement_field = self._fields.get('engagement_location')
        payroll_field = self._fields.get('payroll_location')
        employment_field = self._fields.get('employment_type')

        # Temporarily disable selection validation
        if engagement_field:
            original_eng = engagement_field.selection
            engagement_field.selection = None
        if payroll_field:
            original_pay = payroll_field.selection
            payroll_field.selection = None
        if employment_field:
            original_emp = employment_field.selection
            employment_field.selection = None

        try:
            res = super(HrEmployeeInherit, self).create(vals)
        finally:
            # Restore selections
            if engagement_field:
                engagement_field.selection = original_eng
            if payroll_field:
                payroll_field.selection = original_pay
            if employment_field:
                employment_field.selection = original_emp

        return res

    def write(self, vals):
        """Override to accept any string value from API"""
        # Store original field definitions
        engagement_field = self._fields.get('engagement_location')
        payroll_field = self._fields.get('payroll_location')
        employment_field = self._fields.get('employment_type')

        # Temporarily disable selection validation
        if engagement_field:
            original_eng = engagement_field.selection
            engagement_field.selection = None
        if payroll_field:
            original_pay = payroll_field.selection
            payroll_field.selection = None
        if employment_field:
            original_emp = employment_field.selection
            employment_field.selection = None

        try:
            res = super(HrEmployeeInherit, self).write(vals)
        finally:
            # Restore selections
            if engagement_field:
                engagement_field.selection = original_eng
            if payroll_field:
                payroll_field.selection = original_pay
            if employment_field:
                employment_field.selection = original_emp

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

        if engagement_norm == 'offshore' and (
                'tcip' in payroll_norm or 'india' in payroll_norm) and emp_type_norm == 'permanent':
            return 'TCIP'

        if engagement_norm == 'offshore' and 'dubaioffshore' in payroll_norm:
            if emp_type_norm in ['permanent', 'temporary']:
                return 'T'

        if engagement_norm in ['onsite',
                               'nearshore'] and 'dubaionsite' in payroll_norm and emp_type_norm == 'permanent':
            return 'P'

        if engagement_norm in ['onsite',
                               'nearshore'] and 'dubaionsite' in payroll_norm and emp_type_norm == 'temporary':
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