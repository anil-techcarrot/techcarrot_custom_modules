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
        store=True,
        help="Unique employee code (e.g., P0001, TCIP0012, BC0005)"
    )

    line_manager_id = fields.Many2one(
        'hr.employee',
        string='Line Manager',
        copy=False
    )

    emp_code = fields.Char(
        string='Emp Code',
        copy=False,
        index=True,
        readonly=True,
        store=True,
        help="Unique employee code (e.g., P0001, TCIP0012, BC0005)"
    )

    # ===============================
    # SELECTION FIELDS (UI)
    # ===============================

    engagement_location = fields.Selection([
        ('onsite', 'Onsite'),
        ('offshore', 'Offshore'),
        ('near_shore', 'Nearshore'),
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

    # ===============================
    # TEXT FIELDS (API SAFE)
    # ===============================

    engagement_location_text = fields.Char(store=True)
    payroll_location_text = fields.Char(store=True)
    employment_type_text = fields.Char(store=True)

    # ===============================
    # SYNC METHODS
    # ===============================

    def _sync_text_to_selection(self, vals):

        maps = {
            'engagement_location': {
                'onsite': 'onsite',
                'offshore': 'offshore',
                'nearshore': 'near_shore',
                'near shore': 'near_shore',
            },
            'payroll_location': {
                'dubai onsite': 'dubai_onsite',
                'dubai-offshore': 'dubai_offshore',
                'dubai offshore': 'dubai_offshore',
                'tcip india': 'tcip_india',
            },
            'employment_type': {
                'permanent': 'permanent',
                'temporary': 'temporary',
                'bootcamp': 'bootcamp',
                'seconded': 'seconded',
                'freelancer': 'freelancer',
            }
        }

        for field, mapping in maps.items():
            text_field = f"{field}_text"

            if text_field in vals and vals[text_field]:
                key = vals[text_field].lower().strip()
                if key in mapping:
                    vals[field] = mapping[key]

        return vals

    @api.onchange('engagement_location', 'payroll_location', 'employment_type')
    def _sync_selection_to_text(self):
        for rec in self:
            rec.engagement_location_text = rec.engagement_location
            rec.payroll_location_text = rec.payroll_location
            rec.employment_type_text = rec.employment_type

    # ===============================
    # CREATE / WRITE
    # ===============================

    @api.model
    def create(self, vals):

        vals = self._sync_text_to_selection(vals)

        res = super().create(vals)

        if res.employee_code:
            res.emp_code = res.employee_code

        return res

    def write(self, vals):

        vals = self._sync_text_to_selection(vals)

        res = super().write(vals)

        if 'employee_code' in vals:
            for record in self:
                if record.employee_code:
                    record.sudo().write({'emp_code': record.employee_code})

        return res

    # ===============================
    # WIZARD OPEN
    # ===============================

    def action_open_code_generation_wizard(self):

        self.ensure_one()

        if self.employee_code:
            raise UserError(_('Employee Code already exists: %s') % self.employee_code)

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

    # ===============================
    # CODE GENERATION LOGIC (UNCHANGED)
    # ===============================

    def _generate_next_employee_code(self):

        prefix = self._get_employee_code_prefix() or 'EMP'

        all_employees = self.search([
            ('employee_code', '!=', False),
            ('employee_code', '=like', f'{prefix}%')
        ])

        max_number = 0
        for emp in all_employees:
            match = re.match(rf'^{re.escape(prefix)}(\d+)$', emp.employee_code)
            if match:
                max_number = max(max_number, int(match.group(1)))

        return f"{prefix}{max_number + 1}"

    def _get_employee_code_prefix(self):

        e = self.engagement_location
        p = self.payroll_location
        t = self.employment_type

        if t == 'seconded':
            return 'PT'
        if t == 'freelancer':
            return 'TFL'

        if t == 'bootcamp':
            if e in ['onsite', 'near_shore'] and p == 'dubai_onsite':
                return 'BC'
            if e == 'offshore' and p == 'dubai_offshore':
                return 'BCO'
            if e == 'offshore' and p == 'tcip_india':
                return 'BCI'

        if e == 'offshore' and p == 'tcip_india' and t == 'permanent':
            return 'TCIP'

        if e == 'offshore' and p == 'dubai_offshore':
            return 'T'

        if e in ['onsite', 'near_shore'] and p == 'dubai_onsite':
            return 'P' if t == 'permanent' else 'T'

        return 'EMP'

    @api.constrains('employee_code')
    def _check_employee_code_unique(self):

        for emp in self:
            if emp.employee_code:
                dup = self.search([
                    ('employee_code', '=', emp.employee_code),
                    ('id', '!=', emp.id)
                ], limit=1)

                if dup:
                    raise UserError(_('Employee Code "%s" already exists!') % emp.employee_code)
