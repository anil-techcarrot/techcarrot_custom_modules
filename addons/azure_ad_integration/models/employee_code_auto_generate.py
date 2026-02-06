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
    employee_code = fields.Char(
        string='Employee Code',
        copy=False,
        index=True,
        readonly=True,
        store=True,
        help="Unique employee code (e.g., P0001, TCIP0012, BC0005)"
    )

    line_manager_id = fields.Many2one('hr.employee', string='Line Manager', copy=False)

    # ✅ HYBRID: Selection for UI, but accepts any string from API
    engagement_location = fields.Selection(
        selection='_get_engagement_location_values',
        string='Engagement Location',
    )

    payroll_location = fields.Selection(
        selection='_get_payroll_location_values',
        string='Payroll'
    )

    employment_type = fields.Selection(
        selection='_get_employment_type_values',
        string='Employment Type'
    )

    def _get_engagement_location_values(self):
        """Dynamic selection values - includes both predefined and custom values"""
        # Base values
        values = [
            ('onsite', 'Onsite'),
            ('offshore', 'Offshore'),
            ('near_shore', 'Nearshore'),
        ]

        # Add any custom values already in database
        custom_values = self.search([
            ('engagement_location', '!=', False),
            ('engagement_location', 'not in', ['onsite', 'offshore', 'near_shore'])
        ]).mapped('engagement_location')

        for val in set(custom_values):
            if val:
                values.append((val, val.title()))

        return values

    def _get_payroll_location_values(self):
        """Dynamic selection values - includes both predefined and custom values"""
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
        """Dynamic selection values - includes both predefined and custom values"""
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

    @api.model
    def create(self, vals):
        """Override to accept any string value from API"""
        # API calls will have these as strings - allow them
        res = super(HrEmployeeInherit, self).create(vals)
        return res

    def write(self, vals):
        """Override to accept any string value from API"""
        res = super(HrEmployeeInherit, self).write(vals)
        return res

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        """Allow selection fields to accept any string"""
        return super(HrEmployeeInherit, self)._name_search(
            name=name, args=args, operator=operator, limit=limit, name_get_uid=name_get_uid
        )

    def action_open_code_generation_wizard(self):
        """Open wizard to generate employee code - ONLY if emp_code is empty"""
        self.ensure_one()

        # ✅ If emp_code already exists (from SharePoint or previous generation), don't allow regeneration
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
            ('emp_code', '=', False),
            ('emp_code', '=', '')
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

            employee.write({'emp_code': new_code})
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
        # Normalize for comparison
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