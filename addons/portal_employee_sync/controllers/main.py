from odoo import http
from odoo.http import request
import json
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class PortalEmployeeSyncController(http.Controller):

    def _verify_api_key(self, api_key):
        return api_key == "a7cf0c4f99a71e9f63c60fda3aa32c0ecba87669"

    def _val(self, value):
        """Extract value from string or SharePoint object"""
        if not value:
            return None

        # Handle SharePoint JSON string
        if isinstance(value, str) and value.startswith('{') and '"Value"' in value:
            try:
                parsed = json.loads(value)
                value = parsed.get('Value') or parsed.get('value')
            except:
                pass

        # Handle dictionary
        if isinstance(value, dict):
            value = value.get('Value') or value.get('value')

        if value is None:
            return None

        value = str(value).strip()
        return value if value else None

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
            except:
                pass
        return None

    def _find_country(self, name):
        name = self._val(name)
        if not name:
            return None
        return request.env['res.country'].sudo().search([
            '|', ('name', 'ilike', name), ('code', 'ilike', name)
        ], limit=1)

    def _find_state(self, name, country_id=None):
        """Fixed: Changed from res.country to res.country.state"""
        name = self._val(name)
        if not name:
            return None
        domain = [('name', 'ilike', name)]
        if country_id:
            domain.append(('country_id', '=', country_id))
        return request.env['res.country.state'].sudo().search(domain, limit=1)

    def _find_language(self, name):
        """Search in language.master table (custom model)"""
        name = self._val(name)
        if not name:
            return None
        try:
            return request.env['language.master'].sudo().search([
                ('name', 'ilike', name)
            ], limit=1)
        except:
            _logger.warning(f"language.master model not found, trying res.lang")
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
        admin_uid = request.env.ref('base.user_admin').id
        dept = request.env(user=admin_uid)['hr.department'].search([('name', '=', name)], limit=1)
        return dept.id if dept else request.env(user=admin_uid)['hr.department'].with_context(
            tracking_disable=True).create({'name': name}).id

    def _get_or_create_job(self, name):
        name = self._val(name)
        if not name:
            return False
        admin_uid = request.env.ref('base.user_admin').id
        job = request.env(user=admin_uid)['hr.job'].search([('name', '=', name)], limit=1)
        return job.id if job else request.env(user=admin_uid)['hr.job'].with_context(tracking_disable=True).create(
            {'name': name}).id

    def _get_or_create_relationship(self, name):
        name = self._val(name)
        if not name:
            return False
        try:
            admin_uid = request.env.ref('base.user_admin').id
            Relationship = request.env(user=admin_uid)['employee.relationship']
            rel = Relationship.search([('name', '=', name)], limit=1)
            if not rel:
                rel = Relationship.with_context(tracking_disable=True).create({'name': name})
            return rel.id
        except:
            _logger.warning(f"Relationship model not found, skipping")
            return False

    @http.route('/odoo/api/employees', type='http', auth='none', methods=['POST'], csrf=False, cors='*')
    def create_employee(self, **kwargs):
        try:
            api_key = request.httprequest.headers.get('api-key')
            if not self._verify_api_key(api_key):
                return self._json_response({'success': False, 'error': 'Invalid API key'}, 401)

            data = json.loads(request.httprequest.data or "{}")
            _logger.info(f"📥 Received: {json.dumps(data, indent=2)}")

            if not self._val(data.get('name')):
                return self._json_response({'success': False, 'error': 'Name is required'}, 400)

            # Get or use admin user context to avoid NULL uid issues
            try:
                # Try to get admin user
                admin_user = request.env.ref('base.user_admin')
                env = request.env(user=admin_user.id)
            except:
                # Fallback to sudo with explicit uid
                env = request.env.with_context(force_company=1).with_user(1)

            Employee = env['hr.employee'].sudo()
            employee = Employee.search([('name', '=', self._val(data.get('name')))], limit=1)

            # EMPLOYEE VALUES
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
                'emergency_contact_person_name': self._val(data.get('emergency_contact_person_name')),
                'emergency_contact_person_phone': self._val(data.get('emergency_contact_person_phone')),
                'emergency_contact_person_name_1': self._val(data.get('emergency_contact_person_name_1')),
                # ✅ FIXED TYPO
                'emergency_contact_person_phone_1': self._val(data.get('emergency_contact_person_phone_1')),
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

            # PRIVATE ADDRESS FIELDS (direct on employee)
            if self._val(data.get('private_street')):
                vals['private_street'] = self._val(data.get('private_street'))
            if self._val(data.get('private_city')):
                vals['private_city'] = self._val(data.get('private_city'))
            if self._val(data.get('private_zip')):
                vals['private_zip'] = self._val(data.get('private_zip'))
            if self._val(data.get('private_phone')):
                vals['private_phone'] = self._val(data.get('private_phone'))

            # RELATIONSHIP
            relationship_id = self._get_or_create_relationship(data.get('relationship_with_emp_id'))
            if relationship_id:
                vals['relationship_with_emp_id'] = relationship_id

            # GENDER & MARITAL
            if self._val(data.get('sex')):
                sex_value = self._val(data.get('sex')).lower()
                # Use 'sex' field (Odoo 14 and earlier) instead of 'gender' (Odoo 15+)
                if sex_value in ['male', 'female', 'other']:
                    vals['sex'] = sex_value
            if self._val(data.get('marital')):
                marital_value = self._val(data.get('marital')).lower()
                if marital_value in ['single', 'married', 'cohabitant', 'widower', 'divorced']:
                    vals['marital'] = marital_value

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
                salary = self._val(data.get('last_salary_per_annum_amt'))
                if salary:
                    vals['last_salary_per_annum_amt'] = float(salary)
            except:
                pass

            # COUNTRIES & STATES
            country = self._find_country(data.get('country_id'))
            if country:
                vals['country_id'] = country.id

            private_country = self._find_country(data.get('private_country_id'))
            if private_country:
                vals['private_country_id'] = private_country.id

            issue_country = self._find_country(data.get('issue_countries_id'))
            if issue_country:
                vals['issue_countries_id'] = issue_country.id

            private_state = self._find_state(
                data.get('private_state_id'),
                private_country.id if private_country else None
            )
            if private_state:
                vals['private_state_id'] = private_state.id

            # MOTHER TONGUE
            lang = self._find_language(data.get('mother_tongue_id'))
            if lang:
                vals['mother_tongue_id'] = lang.id

            # LANGUAGES KNOWN (handle SharePoint JSON)
            langs_raw = self._val(data.get('names'))
            if langs_raw:
                _logger.info(f"✓ Languages raw: {langs_raw}")
                lang_ids = []
                for name in langs_raw.split(','):
                    name = name.strip()
                    if name:
                        lang = self._find_language(name)
                        if lang:
                            lang_ids.append(lang.id)
                        else:
                            _logger.warning(f"Language not found in language.master: {name}")
                if lang_ids:
                    vals['language_known_ids'] = [(6, 0, lang_ids)]

            # LOG FINAL VALUES
            _logger.info(f"📝 Final vals: {json.dumps(vals, default=str, indent=2)}")

            # CREATE OR UPDATE
            if employee:
                employee.write(vals)
                action = "updated"
                _logger.info(f"✅ UPDATED: {employee.name} (ID: {employee.id})")
            else:
                employee = Employee.create(vals)
                action = "created"
                _logger.info(f"✅ CREATED: {employee.name} (ID: {employee.id})")

            # COMMIT using the admin user environment to avoid singleton error
            # employee.env.cr.commit()

            return self._json_response({
                'success': True,
                'action': action,
                'employee_id': employee.id,
                'name': employee.name,
                'email': employee.work_email or ''
            })

        except Exception as e:
            _logger.error(f"❌ ERROR: {str(e)}", exc_info=True)
            return self._json_response({'success': False, 'error': str(e)}, 500)

    def _json_response(self, data, status=200):
        return request.make_response(
            json.dumps(data, indent=2),
            headers=[
                ('Content-Type', 'application/json'),
                ('Access-Control-Allow-Origin', '*'),
            ],
            status=status
        )