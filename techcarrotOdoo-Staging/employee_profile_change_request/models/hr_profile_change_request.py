
# -*- coding: utf-8 -*-
import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Human-readable labels for every editable field
FIELD_LABELS = {
    'work_phone':                       'Work Phone',
    'private_email':                    'Personal Email',
    'private_phone':                    'Personal Phone',
    'private_street':                   'Address Line 1',
    'private_street2':                  'Address Line 2',
    'private_city':                     'City (Private)',
    'private_zip':                      'ZIP Code',
    'whatsapp':                         'WhatsApp',
    'linkedin':                         'LinkedIn',
    'legal_name':                       'Legal Name',
    'facebook_profile':                 'Facebook Profile',
    'insta_profile':                    'Instagram Profile',
    'twitter_profile':                  'Twitter Profile',
    'l10n_in_relationship':             'Emergency Relationship',
    'emergency_phone':                  'Emergency Phone',
    'e_private_city':                   'Emergency Address',
    'emergency_contact_person_name':    'Emergency Contact Name',
    'emergency_contact_person_phone':   'Emergency Contact Phone',
    'alternate_mobile_number':          'Alternate Mobile',
    'emergency_contact_person_name_1':  'Emergency Contact Name (2)',
    'emergency_contact_person_phone_1': 'Emergency Contact Phone (2)',
    'second_alternative_number':        'Second Alternative Number',
    'home_land_line_no':                'Home Land Line',
    'spouse_passport_no':               'Spouse Passport No',
    'spouse_passport_issue_date':       'Spouse Passport Issue Date',
    'spouse_passport_expiry_date':      'Spouse Passport Expiry Date',
    'spouse_visa_no':                   'Spouse Visa No',
    'spouse_visa_expire_date':          'Spouse Visa Expiry Date',
    'spouse_emirates_id_no':            'Spouse Emirates ID No',
    'spouse_emirates_issue_date':       'Spouse Emirates Issue Date',
    'spouse_emirates_id_expiry_date':   'Spouse Emirates ID Expiry Date',
    'spouse_aadhar_no':                 'Spouse Aadhar No',
    'dependent_child_name_1':           'Child 1 Name',
    'dependent_child_dob_1':            'Child 1 DOB',
    'dependent_child_passport_no':      'Child 1 Passport No',
    'dependent_child_passport_issue_date_1':   'Child 1 Passport Issue Date',
    'dependent_child_passport_expiry_date_1':  'Child 1 Passport Expiry Date',
    'dependent_child_visa_no_1':               'Child 1 Visa No',
    'dependent_child_visa_expiration_date_1':  'Child 1 Visa Expiry Date',
    'dependent_child_emirates_id_no_1':        'Child 1 Emirates ID No',
    'dependent_child_emirates_id_issue_date_1':'Child 1 Emirates Issue Date',
    'dependent_child_emirates_id_expiry_date_1':'Child 1 Emirates Expiry Date',
    'dependent_child_aadhar_no_1':             'Child 1 Aadhar No',
    'father_name':                      'Father Name',
    'father_dob':                       'Father DOB',
    'mother_name':                      'Mother Name',
    'mother_dob':                       'Mother DOB',
    'children':                         'No. of Children',
    'career_break_detail':              'Career Break Detail',
    'employee_nominee_name':            'Nominee Name',
    'employee_nominee_contact_no':      'Nominee Contact No',
    'domain_worked':                    'Domains Worked',
    'primary_skill':                    'Primary Skills',
    'secondary_skill':                  'Secondary Skills',
    'tool_used':                        'Tools Used',
    'industry_ref_name':                'Industry Reference Name',
    'industry_ref_email':               'Industry Reference Email',
    'industry_ref_mob_no':              'Industry Reference Mobile',
    'home_country_id_name':             'Home Country ID Name',
    'home_country_id_number':           'Home Country ID Number',
    'mother_tongue_name':               'Mother Tongue',
    'language_known_name':              'Languages Known',
    'u_private_city':                   'Address Inside UAE',
    'current_address':                  'Current Work Address',
    'phone_code_1':                     'ISD Code',
    'house_no':                         'House No / Building',
    'area_name':                        'Area / Town',
    'city':                             'City (Work)',
    'zip_code':                         'Zip Code',
    'experience':                       'Experience',
    'current_role':                     'Current / Additional Role',
    'industry_start_date':              'Industry Start Date',
    'last_organisation_name':           'Last Organisation Name',
    'last_location':                    'Last Location',
    'last_salary_per_annum_currency':   'Last Salary Currency',
    'last_salary_per_annum_amt':        'Last Salary Amount',
    'reason_for_leaving':               'Reason for Leaving',
    'last_report_manager_name':         'Reporting Manager Name',
    'last_report_manager_designation':  'Reporting Manager Designation',
    'last_report_manager_mob_no':       'Reporting Manager Mobile',
    'last_report_manager_mail':         'Reporting Manager Email',
}


class HrProfileChangeRequest(models.Model):
    _name = 'hr.profile.change.request'
    _description = 'Employee Profile Change Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'name'

    # ── Reference ─────────────────────────────────────────────────
    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='New',
    )

    # ── Employee ──────────────────────────────────────────────────
    employee_id = fields.Many2one(
        comodel_name='hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        tracking=True,
    )
    department_id = fields.Many2one(
        comodel_name='hr.department',
        related='employee_id.department_id',
        string='Department',
        store=True,
        readonly=True,
    )

    work_location_id = fields.Many2one(
        related='employee_id.work_location_id',
        string='Work Location',
        store=True,
        readonly=True
    )

    # ── State ─────────────────────────────────────────────────────
    state = fields.Selection(
        selection=[
            ('draft',    'Draft'),
            ('pending',  'Pending HR Review'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        string='Status',
        default='draft',
        tracking=True,
        index=True,
    )

    # ── Submitted Data ────────────────────────────────────────────
    submitted_data = fields.Text(
        string='Submitted Data (JSON)',
        readonly=True,
        help='Raw JSON of all fields submitted by the employee from the portal.',
    )

    # ── Computed diff table ───────────────────────────────────────
    changed_fields_display = fields.Html(
        string='Submitted Changes',
        compute='_compute_changed_fields_display',
        sanitize=False,
    )

    # ── Dates ─────────────────────────────────────────────────────
    submission_date = fields.Datetime(
        string='Submitted On',
        default=fields.Datetime.now,
        readonly=True,
    )
    review_date = fields.Datetime(
        string='Reviewed On',
        readonly=True,
    )

    # ── Review info ───────────────────────────────────────────────
    reviewed_by = fields.Many2one(
        comodel_name='res.users',
        string='Reviewed By',
        readonly=True,
    )
    rejection_reason = fields.Text(
        string='Rejection Reason',
        tracking=True,
    )

    # ── Relations ─────────────────────────────────────────────────
    trail_ids = fields.One2many(
        comodel_name='hr.profile.change.request.trail',
        inverse_name='request_id',
        string='Audit Trail',
        readonly=True,
    )

    # ── Sequence ──────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            name_val = vals.get('name', '')
            # Assign sequence if name is missing, 'New', or any translated variant
            if not name_val or not name_val.startswith('PCR/'):
                seq = self.env['ir.sequence'].sudo().next_by_code(
                    'hr.profile.change.request'
                )
                if seq:
                    vals['name'] = seq
                else:
                    _logger.error(
                        'Sequence hr.profile.change.request not found! '
                        'Record will be saved as "New".'
                    )
        return super().create(vals_list)

    # ── Compute changed fields HTML table ─────────────────────────
    @api.depends('submitted_data', 'employee_id')
    def _compute_changed_fields_display(self):
        for rec in self:
            if not rec.submitted_data:
                rec.changed_fields_display = (
                    '<p class="text-muted">No data submitted yet.</p>'
                )
                continue
            try:
                data = json.loads(rec.submitted_data)
                rows = ''
                for key, new_val in data.items():
                    label = FIELD_LABELS.get(
                        key, key.replace('_', ' ').title()
                    )
                    # safely get current value from employee
                    try:
                        current = getattr(rec.employee_id, key, '') or ''
                        # handle relational fields
                        if hasattr(current, 'name'):
                            current = current.name or ''
                        current = str(current)
                    except Exception:
                        current = '—'

                    new_val_str = str(new_val) if new_val else '—'
                    is_changed = new_val_str != current
                    row_style = (
                        'background:#fffde7;'
                        if is_changed else ''
                    )
                    changed_badge = (
                        '<span style="background:#ff9800;color:white;'
                        'padding:2px 6px;border-radius:3px;'
                        'font-size:11px;">CHANGED</span>'
                        if is_changed else ''
                    )
                    rows += f'''
                        <tr style="{row_style}">
                            <td style="padding:8px 12px;border:1px solid #ddd;">
                                <strong>{label}</strong>
                            </td>
                            <td style="padding:8px 12px;border:1px solid #ddd;
                                       color:#888;">{current or '—'}</td>
                            <td style="padding:8px 12px;border:1px solid #ddd;
                                       color:#2e7d32;font-weight:600;">
                                {new_val_str}
                            </td>
                            <td style="padding:8px 12px;border:1px solid #ddd;
                                       text-align:center;">{changed_badge}</td>
                        </tr>
                    '''
                rec.changed_fields_display = f'''
                    <div style="overflow-x:auto;">
                    <table style="width:100%;border-collapse:collapse;
                                  font-size:13px;font-family:Arial,sans-serif;">
                        <thead>
                            <tr style="background:#4e73df;color:white;">
                                <th style="padding:10px 12px;text-align:left;
                                           border:1px solid #3a5ec9;">Field</th>
                                <th style="padding:10px 12px;text-align:left;
                                           border:1px solid #3a5ec9;">Current Value</th>
                                <th style="padding:10px 12px;text-align:left;
                                           border:1px solid #3a5ec9;">Submitted Value</th>
                                <th style="padding:10px 12px;text-align:center;
                                           border:1px solid #3a5ec9;">Status</th>
                            </tr>
                        </thead>
                        <tbody>{rows}</tbody>
                    </table>
                    </div>
                    <p style="font-size:11px;color:#999;margin-top:8px;">
                        ⚠ Highlighted rows indicate values that differ from current record.
                    </p>
                '''
            except Exception as e:
                rec.changed_fields_display = (
                    f'<p class="text-danger">Error reading submitted data: {e}</p>'
                )

    # ── Submit (called from portal controller) ────────────────────
    def action_submit(self):
        self.ensure_one()
        self.write({'state': 'pending'})
        # ── Save submitted data to employee so portal can show overlay ──
        self.employee_id.sudo().write({
            'last_portal_submission': self.submitted_data,
            'last_submission_state': 'pending',
        })
        self._add_trail(
            action='submitted',
            note=f'Request submitted by {self.employee_id.name}',
        )
        self._send_mail_to_hr()
        return True

    # ── Approve ───────────────────────────────────────────────────
    def action_approve(self):
        self.ensure_one()
        if self.state != 'pending':
            raise UserError(_('Only pending requests can be approved.'))

        try:
            data = json.loads(self.submitted_data or '{}')
        except Exception:
            raise UserError(_(
                'Submitted data is corrupted. Cannot apply changes.'
            ))

        # Fields to skip when writing to hr.employee
        skip_fields = {'csrf_token', 'submit'}

        write_vals = {
            k: v
            for k, v in data.items()
            if k not in skip_fields and v is not None and v != ''
        }

        # Type coercions
        int_fields = {'children'}
        float_fields = {'last_salary_per_annum_amt'}

        for f in int_fields:
            if f in write_vals:
                try:
                    write_vals[f] = int(write_vals[f])
                except (ValueError, TypeError):
                    write_vals.pop(f, None)

        for f in float_fields:
            if f in write_vals:
                try:
                    write_vals[f] = float(write_vals[f])
                except (ValueError, TypeError):
                    write_vals.pop(f, None)

        # Write to employee record
        self.employee_id.sudo().write(write_vals)
        _logger.info(
            'Profile change request %s approved. '
            'Wrote %d fields to employee %s.',
            self.name, len(write_vals), self.employee_id.name,
        )

        self.write({
            'state':       'approved',
            'reviewed_by': self.env.user.id,
            'review_date': fields.Datetime.now(),
        })
        self._add_trail(
            action='approved',
            note=f'Approved by {self.env.user.name}. '
                 f'{len(write_vals)} field(s) written to employee record.',
        )
        self._send_mail_to_employee('approved')
        # ── Clear overlay after approval ──
        self.employee_id.sudo().write({
            'last_portal_submission': False,
            'last_submission_state': False,
        })
        return True

    # ── Reject (opens wizard) ─────────────────────────────────────
    def action_reject(self):
        self.ensure_one()
        return {
            'type':      'ir.actions.act_window',
            'name':      _('Reject Profile Change Request'),
            'res_model': 'hr.profile.change.request.reject.wizard',
            'view_mode': 'form',
            'target':    'new',
            'context':   {'default_request_id': self.id},
        }

    # ── Re-open rejected request ──────────────────────────────────
    def action_reset_to_pending(self):
        self.ensure_one()
        if self.state != 'rejected':
            raise UserError(_('Only rejected requests can be re-opened.'))
        self.write({
            'state':            'pending',
            'rejection_reason': False,
            'reviewed_by':      False,
            'review_date':      False,
        })
        self._add_trail(
            action='reopened',
            note=f'Re-opened by {self.env.user.name}',
        )
        return True

    # ── Helpers ───────────────────────────────────────────────────
    def _add_trail(self, action, note, reason=None):
        self.env['hr.profile.change.request.trail'].sudo().create({
            'request_id':  self.id,
            'action':      action,
            'note':        note,
            'reason':      reason or '',
            'user_id':     self.env.user.id,
            'action_date': fields.Datetime.now(),
        })

    def _send_mail_to_hr(self):
        try:
            hr_person = self.employee_id.hr_manager_id
            hr_email = hr_person.work_email if hr_person else None

            if not hr_email:
                _logger.warning(
                    'No HR manager assigned for employee %s. '
                    'Please set Assigned HR Manager on the employee record.',
                    self.employee_id.name
                )
                return

            mail = self.env['mail.mail'].sudo().create({
                'subject': (
                    f'New Profile Change Request: '
                    f'{self.name} — {self.employee_id.name}'
                ),
                'email_to': hr_email,
                'email_from': (
                        self.employee_id.company_id.email
                        or 'notifications@techcarrot-fz-llc1.odoo.com'
                ),
                'auto_delete': False,
                'body_html': f'''
                    <div style="font-family:Arial,sans-serif;max-width:600px;">
                        <div style="background:#4e73df;padding:20px;">
                            <h2 style="color:white;margin:0;">
                                📋 New Profile Change Request
                            </h2>
                        </div>
                        <div style="padding:20px;background:#f9f9f9;">
                            <p>Dear {hr_person.name},</p>
                            <p>
                                <b>{self.employee_id.name}</b> has submitted
                                a profile update request that requires your review.
                            </p>
                            <table style="width:100%;border-collapse:collapse;">
                                <tr style="background:#eef2ff;">
                                    <td style="padding:8px;border:1px solid #ddd;
                                               font-weight:bold;width:35%;">
                                        Reference
                                    </td>
                                    <td style="padding:8px;border:1px solid #ddd;">
                                        {self.name}
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding:8px;border:1px solid #ddd;
                                               font-weight:bold;">Employee</td>
                                    <td style="padding:8px;border:1px solid #ddd;">
                                        {self.employee_id.name}
                                    </td>
                                </tr>
                                <tr style="background:#eef2ff;">
                                    <td style="padding:8px;border:1px solid #ddd;
                                               font-weight:bold;">Department</td>
                                    <td style="padding:8px;border:1px solid #ddd;">
                                        {self.department_id.name or '—'}
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding:8px;border:1px solid #ddd;
                                               font-weight:bold;">Submitted On</td>
                                    <td style="padding:8px;border:1px solid #ddd;">
                                        {self.submission_date}
                                    </td>
                                </tr>
                            </table>
                            <p>
                                Please login to Odoo →
                                Human Resources → Profile Change Requests
                                to review and approve or reject.
                            </p>
                        </div>
                    </div>
                ''',
            })
            mail.sudo().send()
            _logger.info(
                'HR notification sent to %s for request %s',
                hr_email, self.name
            )
        except Exception as e:
            _logger.warning(
                'Failed to send HR notification: %s', e
            )

    def _send_mail_to_employee(self, status):
        try:
            emp_email = self.employee_id.work_email or self.employee_id.private_email
            if not emp_email:
                return
            if status == 'approved':
                subject = f'Profile Update Approved - {self.name}'
                body = f'<p>Dear <b>{self.employee_id.name}</b>,</p><p>Your request <b>{self.name}</b> has been <b style="color:green">APPROVED</b>. Your record has been updated.</p>'
            else:
                subject = f'Profile Update Rejected - {self.name}'
                body = f'<p>Dear <b>{self.employee_id.name}</b>,</p><p>Your request <b>{self.name}</b> has been <b style="color:red">REJECTED</b>.</p><p>Reason: {self.rejection_reason or "No reason provided"}</p>'
            mail = self.env['mail.mail'].sudo().create({
                'subject': subject,
                'email_to': emp_email,
                'email_from': 'notifications@techcarrot-fz-llc1.odoo.com',
                'auto_delete': False,
                'body_html': body,
            })
            mail.sudo().send()
            _logger.info('Employee notification sent to %s', emp_email)
        except Exception as e:
            _logger.warning('Failed to send employee notification: %s', e)







