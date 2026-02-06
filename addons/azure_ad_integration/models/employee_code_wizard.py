from odoo import models, fields, api, _
from odoo.exceptions import UserError
import re


class EmployeeCodeGenerationWizard(models.TransientModel):
    _name = 'employee.code.generation.wizard'
    _description = 'Employee Code Generation Wizard'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        readonly=True
    )

    employee_name = fields.Char(
        related='employee_id.name',
        string='Employee Name',
        readonly=True
    )

    engagement_location = fields.Selection(
        [
            ('onsite', 'Onsite'),
            ('offshore', 'Offshore'),
            ('near_shore', 'Nearshore'),
        ],
        string='Engagement Location',
        required=True
    )

    payroll_location = fields.Selection([
        ('dubai_onsite', 'Dubai- Onsite'),
        ('dubai_offshore', 'Dubai-Offshore'),
        ('tcip_india', 'TCIP India'),
    ], string='Payroll', required=True)

    employment_type = fields.Selection([
        ('permanent', 'Permanent'),
        ('temporary', 'Temporary'),
        ('bootcamp', 'Bootcamp'),
        ('seconded', 'Seconded'),
        ('freelancer', 'Freelancer'),
    ], string='Employment Type', required=True)

    preview_code = fields.Char(
        string='Preview Code',
        readonly=True,
        compute='_compute_preview_code'
    )

    # ---------------------------------------------------
    # Preview Code
    # ---------------------------------------------------

    @api.depends('engagement_location', 'payroll_location', 'employment_type')
    def _compute_preview_code(self):
        for wizard in self:
            if wizard.engagement_location and wizard.payroll_location and wizard.employment_type:
                prefix = wizard._get_employee_code_prefix()
                next_number = wizard._get_next_number(prefix)
                wizard.preview_code = f"{prefix}{next_number}"
            else:
                wizard.preview_code = "Select all fields to preview"

    # ---------------------------------------------------
    # Prefix Logic
    # ---------------------------------------------------

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

        if engagement in ['onsite', 'near_shore'] and payroll == 'dubai_onsite' and emp_type == 'permanent':
            return 'P'

        if engagement in ['onsite', 'near_shore'] and payroll == 'dubai_onsite' and emp_type == 'temporary':
            return 'T'

        return 'EMP'

    # ---------------------------------------------------
    # Get Next Number
    # ---------------------------------------------------

    def _get_next_number(self, prefix):

        all_employees = self.env['hr.employee'].search([
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

        return max_number + 1

    # ---------------------------------------------------
    # Generate Code
    # ---------------------------------------------------

    def action_generate_code(self):
        self.ensure_one()

        if self.employee_id.emp_code:
            raise UserError(_(
                'Employee Code already exists: %s\n'
                'Cannot generate a new code for employee: %s'
            ) % (self.employee_id.emp_code, self.employee_id.name))

        prefix = self._get_employee_code_prefix()
        next_number = self._get_next_number(prefix)
        new_code = f"{prefix}{next_number}"

        # ----------------------------------------
        # Convert selection KEY -> LABEL (important)
        # ----------------------------------------

        engagement_label = dict(
            self.fields_get(['engagement_location'])['engagement_location']['selection']
        ).get(self.engagement_location)

        payroll_label = dict(
            self.fields_get(['payroll_location'])['payroll_location']['selection']
        ).get(self.payroll_location)

        employment_label = dict(
            self.fields_get(['employment_type'])['employment_type']['selection']
        ).get(self.employment_type)

        # ----------------------------------------
        # Write into employee (Char fields)
        # ----------------------------------------

        self.employee_id.write({
            'emp_code': new_code,
            'engagement_location': engagement_label,
            'payroll_location': payroll_label,
            'employment_type': employment_label,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Employee Code "%s" generated successfully for %s!') % (
                    new_code, self.employee_id.name),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
