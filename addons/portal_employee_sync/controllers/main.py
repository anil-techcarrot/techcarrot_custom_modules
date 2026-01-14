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
    # SAFE VALUE (STRING / SHAREPOINT OBJECT)
    # ---------------------------------------------------------
    def _val(self, value):
        if not value:
            return None
        if isinstance(value, dict):
            value = value.get('Value') or value.get('value')
        if value is None:
            return None
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
                return datetime.strptime(value, fmt).strftime('%Y-%m-%d')
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

    def _find_language(self, name):
        name = self._val(name)
        if not name:
            return None
        return request.env['res.lang'].sudo().search([
            '|', '|', '|',
            ('name', 'ilike', name),
            ('code', 'ilike', name),
            ('iso_code', 'ilike', name),
            ('name', '=', name)
        ], limit=1)

    def _get_or_create_department(self, name):
        name = self._val(name)
        if not name:
            return False
        dept = request.env['hr.department'].sudo().search([('name', '=', name)], limit=1)
        if not dept:
            dept = request.env['hr.department'].sudo().create({'name': name})
        return dept.id

    def _get_or_create_job(self, name):
        name = self._val(name)
        if not name:
            return False
        job = request.env['hr.job'].sudo().search([('name', '=', name)], limit=1)
        if not job:
            job = request.env['hr.job'].sudo().create({'name': name})
        return job.id

    # ---------------------------------------------------------
    # MAIN API
    # ---------------------------------------------------------
    @http.route('/api/employees', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def create_employee(self, **kwargs):

        try:
            api_key = (
                request.httprequest.headers.get('api-key')
                or request.httprequest.headers.get('Authorization', '').replace('Bearer ', '')
            )

            if not self._verify_api_key(api_key):
                return self._json_response({'success': False, 'error': 'Invalid API key'}, 401)

            data = json.loads(request.httprequest.data or "{}")

            if not self._val(data.get('name')):
                return self._json_response({'success': False, 'error': 'Name is required'}, 400)

            Employee = request.env['hr.employee'].sudo()

            employee = None
            if self._val(data.get('employee_id')):
                employee = Employee.search([
                    ('sharepoint_employee_id', '=', self._val(data.get('employee_id')))
                ], limit=1)

            if not employee:
                employee = Employee.search([('name', '=', data['name'])], limit=1)

            vals = {
                'name': self._val(data.get('name')),
                'sharepoint_employee_id': self._val(data.get('employee_id')),
                'work_email': self._val(data.get('email')),
                'mobile_phone': self._val(data.get('phone')),
                'department_id': self._get_or_create_department(data.get('department')),
                'job_id': self._get_or_create_job(data.get('job_title')),

                'employee_first_name': self._val(data.get('employee_first_name')),
                'employee_middle_name': self._val(data.get('employee_middle_name')),
                'employee_last_name': self._val(data.get('employee_last_name')),

                'private_email': self._val(data.get('private_email')),
                'place_of_birth': self._val(data.get('place_of_birth')),

                'private_street': self._val(data.get('private_street')),
                'private_city': self._val(data.get('private_city')),
                'private_zip': self._val(data.get('private_zip')),
                'private_phone': self._val(data.get('private_phone')),

                'passport_id': self._val(data.get('passport_id')),
                'primary_skill': self._val(data.get('primary_skill')),
                'secondary_skill': self._val(data.get('secondary_skill')),
                'last_organisation_name': self._val(data.get('last_organisation_name')),
                'current_address': self._val(data.get('current_address')),
                'notice_period': self._val(data.get('notice_period')),
                'reason_for_leaving': self._val(data.get('reason_for_leaving')),

                'last_report_manager_name': self._val(data.get('last_report_manager_name')),
                'last_report_manager_designation': self._val(data.get('last_report_manager_designation')),
                'last_report_manager_mail': self._val(data.get('last_report_manager_mail')),
                'last_report_manager_mob_no': self._val(data.get('last_report_manager_mob_no')),

                'industry_ref_name': self._val(data.get('industry_ref_name')),
                'industry_ref_email': self._val(data.get('industry_ref_email')),
                'industry_ref_mob_no': self._val(data.get('industry_ref_mob_no')),

                'degree_certificate_legal': self._val(data.get('degree_certificate_legal')),
                'degree_name': self._val(data.get('degree_name')),
                'institute_name': self._val(data.get('institute_name')),
                'score': self._val(data.get('score')),
                'period_in_company': self._val(data.get('period_in_company')),
            }

            # GENDER
            gender = self._val(data.get('sex'))
            if gender:
                vals['sex'] = gender.lower()

            # MARITAL
            marital = self._val(data.get('marital'))
            if marital:
                vals['marital'] = marital.lower()

            # DATES
            vals.update({
                'birthday': self._parse_date(data.get('birthday')),
                'issue_date': self._parse_date(data.get('issue_date')),
                'passport_expiration_date': self._parse_date(data.get('passport_expiration_date')),
                'leave_date_from': self._parse_date(data.get('leave_date_from')),
                'start_date_of_degree': self._parse_date(data.get('start_date_of_degree')),
                'completion_date_of_degree': self._parse_date(data.get('completion_date_of_degree')),
            })

            # SALARY
            try:
                vals['last_salary_per_annum_amt'] = float(data.get('last_salary_per_annum_amt'))
            except Exception:
                pass

            # COUNTRIES
            country = self._find_country(data.get('country_id'))
            if country:
                vals['country_id'] = country.id

            private_country = self._find_country(data.get('private_country_id'))
            if private_country:
                vals['private_country_id'] = private_country.id

            issue_country = self._find_country(data.get('issue_countries_id'))
            if issue_country:
                vals['issue_countries_id'] = issue_country.id

            # MOTHER TONGUE
            lang = self._find_language(data.get('mother_tongue_id'))
            if lang:
                vals['mother_tongue_id'] = lang.id

            # LANGUAGES KNOWN
            langs_raw = self._val(data.get('names'))
            if langs_raw:
                lang_ids = []
                for name in langs_raw.split(','):
                    lang = self._find_language(name)
                    if lang:
                        lang_ids.append(lang.id)
                if lang_ids:
                    vals['language_known_ids'] = [(6, 0, lang_ids)]

            # CREATE / UPDATE
            if employee:
                employee.write(vals)
                action = "updated"
            else:
                employee = Employee.create(vals)
                action = "created"

            return self._json_response({
                'success': True,
                'action': action,
                'employee_id': employee.id,
                'name': employee.name,
                'email': employee.work_email or ''
            })

        except Exception as e:
            _logger.error("EMPLOYEE SYNC ERROR", exc_info=True)
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
