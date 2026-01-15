from odoo import http
from odoo.http import request
import json
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class PortalEmployeeSyncController(http.Controller):

    # ---------------------------------------------------------
    # API KEY
    # ---------------------------------------------------------
    def _verify_api_key(self, api_key):
        return api_key == "a7cf0c4f99a71e9f63c60fda3aa32c0ecba87669"

    # ---------------------------------------------------------
    # SAFE VALUE
    # ---------------------------------------------------------
    def _val(self, value):
        if not value:
            return None
        if isinstance(value, dict):
            value = value.get('Value') or value.get('value')
        value = str(value).strip()
        return value if value else None

    # ---------------------------------------------------------
    # DATE PARSER
    # ---------------------------------------------------------
    def _parse_date(self, value):
        value = self._val(value)
        if not value:
            return None

        formats = [
            '%Y-%m-%d', '%d-%m-%Y', '%m/%d/%Y', '%d/%m/%Y',
            '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ'
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).date()
            except Exception:
                pass
        return None

    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------
    def _find_country(self, name):
        name = self._val(name)
        if not name:
            return None
        return request.env['res.country'].sudo().search([
            '|', ('name', 'ilike', name), ('code', 'ilike', name)
        ], limit=1)

    def _find_state(self, name, country_id=None):
        name = self._val(name)
        if not name:
            return None
        domain = [('name', 'ilike', name)]
        if country_id:
            domain.append(('country_id', '=', country_id))
        return request.env['res.country.state'].sudo().search(domain, limit=1)

    def _get_or_create_department(self, name):
        name = self._val(name)
        if not name:
            return False
        dept = request.env['hr.department'].sudo().search([('name', '=', name)], limit=1)
        return dept.id if dept else request.env['hr.department'].sudo().create({'name': name}).id

    def _get_or_create_job(self, name):
        name = self._val(name)
        if not name:
            return False
        job = request.env['hr.job'].sudo().search([('name', '=', name)], limit=1)
        return job.id if job else request.env['hr.job'].sudo().create({'name': name}).id

    # ---------------------------------------------------------
    # MAIN API
    # ---------------------------------------------------------
    @http.route('/api/employees', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def create_employee(self, **kwargs):

        try:
            api_key = request.httprequest.headers.get('api-key')
            if not self._verify_api_key(api_key):
                return self._json_response({'success': False, 'error': 'Invalid API key'}, 401)

            data = json.loads(request.httprequest.data or "{}")

            if not self._val(data.get('name')):
                return self._json_response({'success': False, 'error': 'Name is required'}, 400)

            Employee = request.env['hr.employee'].sudo()
            employee = Employee.search([('name', '=', self._val(data.get('name')))], limit=1)

            # ---------------- EMPLOYEE VALUES ----------------
            vals = {
                'name': self._val(data.get('name')),
                'work_email': self._val(data.get('email')),
                'mobile_phone': self._val(data.get('phone')),
                'department_id': self._get_or_create_department(data.get('department')),
                'job_id': self._get_or_create_job(data.get('job_title')),

                'employee_first_name': self._val(data.get('employee_first_name')),
                'employee_middle_name': self._val(data.get('employee_middle_name')),
                'employee_last_name': self._val(data.get('employee_last_name')),

                'private_email': self._val(data.get('private_email')),
                'place_of_birth': self._val(data.get('place_of_birth')),

                'passport_id': self._val(data.get('passport_id')),
                'primary_skill': self._val(data.get('primary_skill')),
                'secondary_skill': self._val(data.get('secondary_skill')),
                'last_organisation_name': self._val(data.get('last_organisation_name')),
                'current_address': self._val(data.get('current_address')),
                'notice_period': self._val(data.get('notice_period')),
                'reason_for_leaving': self._val(data.get('reason_for_leaving')),

                # ✅ CUSTOM EMERGENCY FIELDS
                'relationship_with_emp_id': self._val(data.get('relationship_with_emp_id')),
                'emergency_contact_person_name_1': self._val(data.get('emergency_contact_person_name_1')),
                'emergency_contact_person_phone_1': self._val(data.get('emergency_contact_person_phone_1')),
            }

            if self._val(data.get('sex')):
                vals['sex'] = self._val(data.get('sex')).lower()

            if self._val(data.get('marital')):
                vals['marital'] = self._val(data.get('marital')).lower()

            vals.update({
                'birthday': self._parse_date(data.get('birthday')),
                'issue_date': self._parse_date(data.get('issue_date')),
                'passport_expiration_date': self._parse_date(data.get('passport_expiration_date')),
            })

            if employee:
                employee.write(vals)
                action = "updated"
            else:
                employee = Employee.create(vals)
                action = "created"

            # ---------------- PRIVATE ADDRESS ----------------
            private_country = self._find_country(data.get('private_country_id'))
            private_state = self._find_state(
                data.get('private_state_id'),
                private_country.id if private_country else None
            )

            address_vals = {
                'street': self._val(data.get('private_street')),
                'city': self._val(data.get('private_city')),
                'zip': self._val(data.get('private_zip')),
                'phone': self._val(data.get('private_phone')),
                'email': self._val(data.get('private_email')),
                'country_id': private_country.id if private_country else False,
                'state_id': private_state.id if private_state else False,
            }

            address_vals = {k: v for k, v in address_vals.items() if v}

            if address_vals:
                if employee.address_home_id:
                    employee.address_home_id.write(address_vals)
                else:
                    partner = request.env['res.partner'].sudo().create(address_vals)
                    employee.address_home_id = partner.id

            return self._json_response({
                'success': True,
                'action': action,
                'employee_id': employee.id,
                'name': employee.name
            })

        except Exception as e:
            _logger.exception("EMPLOYEE SYNC ERROR")
            return self._json_response({'success': False, 'error': str(e)}, 500)

    # ---------------------------------------------------------
    # RESPONSE
    # ---------------------------------------------------------
    def _json_response(self, data, status=200):
        return request.make_response(
            json.dumps(data, indent=2),
            headers=[('Content-Type', 'application/json')],
            status=status
        )
