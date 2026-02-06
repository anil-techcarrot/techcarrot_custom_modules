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
        if isinstance(value, str) and value.startswith('{'):
            try:
                if '"Value"' in value or '"value"' in value:
                    parsed = json.loads(value)
                    value = parsed.get('Value') or parsed.get('value')
                    _logger.info(f"✓ Extracted from SharePoint JSON: {value}")
            except Exception as e:
                _logger.warning(f"Failed to parse as JSON, using as-is: {e}")
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
            '%Y-%m-%d', '%d-%m-%Y', '%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d',
            '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ'
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt).date()
            except:
                pass
        return None

    def _find_country(self, name):
        """Find country by name or code - exact match priority"""
        name = self._val(name)
        if not name:
            return None

        name = name.strip()

        # First: Try exact code match (IN, AE, etc.)
        country = request.env['res.country'].sudo().search([
            ('code', '=', name.upper())
        ], limit=1)
        if country:
            return country

        # Second: Try EXACT name match (case insensitive)
        country = request.env['res.country'].sudo().search([
            ('name', '=ilike', name)
        ], limit=1)
        if country:
            return country

        # Third: Try partial match as fallback
        country = request.env['res.country'].sudo().search([
            ('name', 'ilike', name)
        ], limit=1, order='name')

        return country if country else None

    def _find_state(self, name, country_id=None):
        name = self._val(name)
        if not name:
            return None
        domain = [('name', 'ilike', name)]
        if country_id:
            domain.append(('country_id', '=', country_id))
        return request.env['res.country.state'].sudo().search(domain, limit=1)

    def _find_language_in_res_lang(self, name):
        """Search in res.lang table for language"""
        name = self._val(name)
        if not name:
            return None

        name = name.strip()

        # Language name to code mapping
        language_map = {
            'english': 'en_US',
            'hindi': 'hi_IN',
            'telugu': 'te_IN',
            'tamil': 'ta_IN',
            'kannada': 'kn_IN',
            'malayalam': 'ml_IN',
            'marathi': 'mr_IN',
            'bengali': 'bn_IN',
            'gujarati': 'gu_IN',
            'punjabi': 'pa_IN',
            'urdu': 'ur_IN',
            'arabic': 'ar_001',
            'french': 'fr_FR',
            'german': 'de_DE',
            'spanish': 'es_ES',
            'chinese': 'zh_CN',
            'japanese': 'ja_JP',
        }

        try:
            # First: Try exact code match
            lang = request.env['res.lang'].sudo().search([
                ('code', '=', name)
            ], limit=1)
            if lang:
                return lang

            # Second: Try mapping
            name_lower = name.lower()
            if name_lower in language_map:
                code = language_map[name_lower]
                lang = request.env['res.lang'].sudo().search([
                    ('code', '=', code)
                ], limit=1)
                if lang:
                    return lang

            # Third: Try exact name match
            lang = request.env['res.lang'].sudo().search([
                ('name', '=ilike', name)
            ], limit=1)
            if lang:
                return lang

            # Fourth: Try partial name match
            lang = request.env['res.lang'].sudo().search([
                ('name', 'ilike', name)
            ], limit=1)
            if lang:
                return lang

            return None

        except Exception as e:
            _logger.error(f"❌ Error searching res.lang: {e}", exc_info=True)
            return None

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

    def _get_or_create_relationship(self, name):
        name = self._val(name)
        if not name:
            return False
        try:
            Relationship = request.env['employee.relationship'].sudo()
            rel = Relationship.search([('name', '=', name)], limit=1)
            if not rel:
                rel = Relationship.create({'name': name})
            return rel.id
        except:
            _logger.warning(f"Relationship model not found, skipping")
            return False

    @http.route('/odoo/api/employees', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def create_employee(self, **kwargs):
        # Set admin user context
        admin_user = request.env.ref('base.user_admin')
        request.update_env(user=admin_user.id)

        try:
            api_key = request.httprequest.headers.get('api-key')
            if not self._verify_api_key(api_key):
                return self._json_response({'success': False, 'error': 'Invalid API key'}, 401)

            data = json.loads(request.httprequest.data or "{}")
            _logger.info(f"📥 Received: {json.dumps(data, indent=2)}")

            if not self._val(data.get('name')):
                return self._json_response({'success': False, 'error': 'Name is required'}, 400)

            Employee = request.env['hr.employee']
            employee = Employee.search([('name', '=', self._val(data.get('name')))], limit=1)

            # ========== EXTRACT FIELDS - PASS AS-IS TO MODEL ==========
            # Model's create/write will auto-normalize these
            engagement_location_raw = self._val(data.get('engagement_location'))
            payroll_location_raw = self._val(data.get('payroll_location'))
            employment_type_raw = self._val(data.get('employment_type'))

            _logger.info(f"📝 Fields from SharePoint:")
            _logger.info(f"   engagement_location: '{engagement_location_raw}'")
            _logger.info(f"   payroll_location: '{payroll_location_raw}'")
            _logger.info(f"   employment_type: '{employment_type_raw}'")

            # EMPLOYEE VALUES
            vals = {
                'name': self._val(data.get('name')),
                'work_email': self._val(data.get('email')),
                'mobile_phone': self._val(data.get('phone')),
                'emp_code': self._val(data.get('employee_code')),
                'total_it_experience': self._val(data.get('total_it_experience')),
                'alternate_mobile_number': self._val(data.get('alternate_mobile_number')),
                'second_alternative_number': self._val(data.get('second_alternative_number')),
                'last_location': self._val(data.get('last_location')),
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

            # Add the three critical fields - model will normalize them
            if engagement_location_raw:
                vals['engagement_location'] = engagement_location_raw
            if payroll_location_raw:
                vals['payroll_location'] = payroll_location_raw
            if employment_type_raw:
                vals['employment_type'] = employment_type_raw

            # Line Manager
            line_manager = self._find_employee(data.get('line_manager'))
            if line_manager:
                vals['line_manager_id'] = line_manager.id

            # Second relation with employee
            second_relation_value = self._val(data.get('second_relation_with_employee'))
            if second_relation_value:
                vals['second_relation_with_employee'] = second_relation_value

            # PRIVATE ADDRESS
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
                'expiry_date': self._parse_date(data.get('expiry_date')),
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
            mother_tongue = self._find_language_in_res_lang(data.get('mother_tongue_id'))
            if mother_tongue:
                vals['mother_tongue_id'] = mother_tongue.id

            # ========== PROCESS LANGUAGES KNOWN ==========
            langs_raw_data = (
                    data.get('language_known_ids') or
                    data.get('names') or
                    data.get('languages') or
                    data.get('language_known')
            )

            langs_raw = self._val(langs_raw_data)
            language_ids_to_set = []

            if langs_raw:
                lang_names = [name.strip() for name in langs_raw.split(',') if name.strip()]
                _logger.info(f"📝 Processing {len(lang_names)} language(s): {lang_names}")

                for name in lang_names:
                    lang_obj = self._find_language_in_res_lang(name)
                    if lang_obj:
                        language_ids_to_set.append(lang_obj.id)
                        _logger.info(f"✓ Added: {lang_obj.name} (ID: {lang_obj.id})")

            # CREATE OR UPDATE EMPLOYEE
            # Model's create/write methods will auto-normalize the selection fields
            if employee:
                _logger.info(f"🔄 UPDATING: {employee.name} (ID: {employee.id})")
                employee.write(vals)
                action = "updated"
            else:
                _logger.info(f"➕ CREATING new employee")
                employee = Employee.with_context(auto_generate_code=False).create(vals)
                action = "created"

            _logger.info(f"✓ After save - normalized values:")
            _logger.info(f"   engagement_location: '{employee.engagement_location}'")
            _logger.info(f"   payroll_location: '{employee.payroll_location}'")
            _logger.info(f"   employment_type: '{employee.employment_type}'")

            # SET LANGUAGES
            if language_ids_to_set:
                try:
                    employee.write({'language_known_ids': [(6, 0, language_ids_to_set)]})
                    employee.invalidate_cache(['language_known_ids'])
                    _logger.info(f"✓ Languages saved: {employee.language_known_ids.mapped('name')}")
                except Exception as e:
                    _logger.error(f"❌ Error setting languages: {e}", exc_info=True)

            # RESPONSE
            response_data = {
                'success': True,
                'action': action,
                'employee_id': employee.id,
                'name': employee.name,
                'email': employee.work_email or '',
                'normalized_fields': {
                    'engagement_location': employee.engagement_location,
                    'payroll_location': employee.payroll_location,
                    'employment_type': employee.employment_type
                }
            }

            _logger.info(f"✅ SUCCESS: {json.dumps(response_data, indent=2)}")
            return self._json_response(response_data)

        except Exception as e:
            _logger.error(f"❌ CRITICAL ERROR: {str(e)}", exc_info=True)
            try:
                request.env.cr.rollback()
            except:
                pass
            return self._json_response({'success': False, 'error': str(e)}, 500)

    def _find_employee(self, name):
        """Find employee by name"""
        name = self._val(name)
        if not name:
            return None
        return request.env['hr.employee'].sudo().search([('name', '=ilike', name)], limit=1)

    def _json_response(self, data, status=200):
        return request.make_response(
            json.dumps(data, indent=2),
            headers=[
                ('Content-Type', 'application/json'),
                ('Access-Control-Allow-Origin', '*'),
            ],
            status=status
        )