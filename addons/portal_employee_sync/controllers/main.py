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
        """Extract value from SharePoint object"""
        if not value:
            return None
        if isinstance(value, str) and value.startswith('{'):
            try:
                if '"Value"' in value or '"value"' in value:
                    parsed = json.loads(value)
                    value = parsed.get('Value') or parsed.get('value')
            except:
                pass
        if isinstance(value, dict):
            value = value.get('Value') or value.get('value')
        if value is None:
            return None
        value = str(value).strip()
        return value if value else None

    def _normalize_engagement_location(self, value):
        """
        Normalize engagement_location to valid Odoo selection value.
        ACCEPTS: onsite, ONSITE, offshore, OFFSHORE, nearshore, near-shore, near_shore, etc.
        RETURNS: 'onsite', 'offshore', 'near-shore', or None (if empty)
        RAISES: ValueError if unrecognized value
        """
        if not value:
            return None  # Empty is OK - field is optional

        raw = str(value).lower().strip()
        clean = raw.replace('-', '').replace('_', '').replace(' ', '')

        if clean == 'onsite':
            _logger.info(f"✓ Normalized engagement_location: '{value}' → 'onsite'")
            return 'onsite'
        elif clean == 'offshore':
            _logger.info(f"✓ Normalized engagement_location: '{value}' → 'offshore'")
            return 'offshore'
        elif clean in ['nearshore', 'nearshore']:
            _logger.info(f"✓ Normalized engagement_location: '{value}' → 'near-shore'")
            return 'near-shore'
        else:
            # REJECT unknown values - prevents data quality issues
            error_msg = (
                f"Invalid engagement_location: '{value}'. "
                f"Must be one of: onsite, offshore, nearshore (case-insensitive, spaces/hyphens OK)"
            )
            _logger.error(f"❌ {error_msg}")
            raise ValueError(error_msg)

    def _normalize_payroll_location(self, value):
        """
        Normalize payroll_location to valid Odoo selection value.
        ACCEPTS: dubai-onsite, Dubai_Onsite, DUBAI ONSITE, tcip india, TCIP-INDIA, etc.
        RETURNS: 'dubai-onsite', 'dubai-offshore', 'tcip-india', or None (if empty)
        RAISES: ValueError if unrecognized value
        """
        if not value:
            return None  # Empty is OK - field is optional

        raw = str(value).lower().strip()
        clean = raw.replace('_', '-').replace(' ', '-')

        if 'dubai' in clean and 'onsite' in clean:
            _logger.info(f"✓ Normalized payroll_location: '{value}' → 'dubai-onsite'")
            return 'dubai-onsite'
        elif 'dubai' in clean and 'offshore' in clean:
            _logger.info(f"✓ Normalized payroll_location: '{value}' → 'dubai-offshore'")
            return 'dubai-offshore'
        elif 'tcip' in clean or 'india' in clean:
            _logger.info(f"✓ Normalized payroll_location: '{value}' → 'tcip-india'")
            return 'tcip-india'
        else:
            # REJECT unknown values
            error_msg = (
                f"Invalid payroll_location: '{value}'. "
                f"Must be one of: dubai-onsite, dubai-offshore, tcip-india (case-insensitive, spaces/hyphens OK)"
            )
            _logger.error(f"❌ {error_msg}")
            raise ValueError(error_msg)

    def _normalize_employment_type(self, value):
        """
        Normalize employment_type to valid Odoo selection value.
        ACCEPTS: PERMANENT, PERMANENt, Permanent, temporary, BOOTCAMP, etc.
        RETURNS: 'permanent', 'temporary', 'bootcamp', 'seconded', 'freelancer', or None (if empty)
        RAISES: ValueError if unrecognized value
        """
        if not value:
            return None  # Empty is OK - field is optional

        raw = str(value).lower().strip()

        valid_types = {
            'permanent': 'permanent',
            'temporary': 'temporary',
            'bootcamp': 'bootcamp',
            'seconded': 'seconded',
            'freelancer': 'freelancer',
            # Add common variations if needed:
            'temp': 'temporary',
            'perm': 'permanent',
        }

        if raw in valid_types:
            normalized = valid_types[raw]
            _logger.info(f"✓ Normalized employment_type: '{value}' → '{normalized}'")
            return normalized
        else:
            # REJECT unknown values
            error_msg = (
                f"Invalid employment_type: '{value}'. "
                f"Must be one of: permanent, temporary, bootcamp, seconded, freelancer (case-insensitive)"
            )
            _logger.error(f"❌ {error_msg}")
            raise ValueError(error_msg)

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
        name = self._val(name)
        if not name:
            return None
        country = request.env['res.country'].sudo().search([('code', '=', name.upper())], limit=1)
        if country:
            return country
        country = request.env['res.country'].sudo().search([('name', '=ilike', name)], limit=1)
        if country:
            return country
        return request.env['res.country'].sudo().search([('name', 'ilike', name)], limit=1, order='name')

    def _find_state(self, name, country_id=None):
        name = self._val(name)
        if not name:
            return None
        domain = [('name', 'ilike', name)]
        if country_id:
            domain.append(('country_id', '=', country_id))
        return request.env['res.country.state'].sudo().search(domain, limit=1)

    def _find_language_in_res_lang(self, name):
        name = self._val(name)
        if not name:
            return None
        language_map = {
            'english': 'en_US', 'hindi': 'hi_IN', 'telugu': 'te_IN', 'tamil': 'ta_IN',
            'kannada': 'kn_IN', 'malayalam': 'ml_IN', 'marathi': 'mr_IN', 'bengali': 'bn_IN',
            'gujarati': 'gu_IN', 'punjabi': 'pa_IN', 'urdu': 'ur_IN', 'arabic': 'ar_001',
            'french': 'fr_FR', 'german': 'de_DE', 'spanish': 'es_ES', 'chinese': 'zh_CN',
            'japanese': 'ja_JP',
        }
        lang = request.env['res.lang'].sudo().search([('code', '=', name)], limit=1)
        if lang:
            return lang
        if name.lower() in language_map:
            code = language_map[name.lower()]
            lang = request.env['res.lang'].sudo().search([('code', '=', code)], limit=1)
            if lang:
                return lang
        lang = request.env['res.lang'].sudo().search([('name', '=ilike', name)], limit=1)
        if lang:
            return lang
        return request.env['res.lang'].sudo().search([('name', 'ilike', name)], limit=1)

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
            return False

    @http.route('/odoo/api/employees', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def create_employee(self, **kwargs):
        admin_user = request.env.ref('base.user_admin')
        request.update_env(user=admin_user.id)

        try:
            api_key = request.httprequest.headers.get('api-key')
            if not self._verify_api_key(api_key):
                return self._json_response({'success': False, 'error': 'Invalid API key'}, 401)

            data = json.loads(request.httprequest.data or "{}")
            _logger.info(f"📥 API Request: {json.dumps(data, indent=2)}")

            if not self._val(data.get('name')):
                return self._json_response({'success': False, 'error': 'Name is required'}, 400)

            Employee = request.env['hr.employee']
            employee = Employee.search([('name', '=', self._val(data.get('name')))], limit=1)

            # ========== NORMALIZE AND VALIDATE FIELDS ==========
            engagement_location_raw = self._val(data.get('engagement_location'))
            payroll_location_raw = self._val(data.get('payroll_location'))
            employment_type_raw = self._val(data.get('employment_type'))
            emp_code_from_sharepoint = self._val(data.get('emp_code'))

            try:
                # These will raise ValueError if invalid
                engagement_location_normalized = self._normalize_engagement_location(engagement_location_raw)
                payroll_location_normalized = self._normalize_payroll_location(payroll_location_raw)
                employment_type_normalized = self._normalize_employment_type(employment_type_raw)
            except ValueError as e:
                # Return clear error to SharePoint
                error_response = {
                    'success': False,
                    'error': str(e),
                    'invalid_data': {
                        'engagement_location': engagement_location_raw,
                        'payroll_location': payroll_location_raw,
                        'employment_type': employment_type_raw
                    }
                }
                _logger.error(f"❌ Validation failed: {json.dumps(error_response, indent=2)}")
                return self._json_response(error_response, 400)

            _logger.info(f"✓ NORMALIZATION SUCCESS:")
            _logger.info(f"   engagement_location: '{engagement_location_raw}' → '{engagement_location_normalized}'")
            _logger.info(f"   payroll_location: '{payroll_location_raw}' → '{payroll_location_normalized}'")
            _logger.info(f"   employment_type: '{employment_type_raw}' → '{employment_type_normalized}'")
            _logger.info(f"   emp_code: '{emp_code_from_sharepoint}'")

            vals = {
                'name': self._val(data.get('name')),
                'work_email': self._val(data.get('email')),
                'mobile_phone': self._val(data.get('phone')),
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

            # Set emp_code from SharePoint
            if emp_code_from_sharepoint:
                vals['emp_code'] = emp_code_from_sharepoint

            # Add VALIDATED classification fields
            if engagement_location_normalized:
                vals['engagement_location'] = engagement_location_normalized
            if payroll_location_normalized:
                vals['payroll_location'] = payroll_location_normalized
            if employment_type_normalized:
                vals['employment_type'] = employment_type_normalized

            # Line Manager
            line_manager = self._find_employee(data.get('line_manager'))
            if line_manager:
                vals['line_manager_id'] = line_manager.id

            # Other fields
            second_relation_value = self._val(data.get('second_relation_with_employee'))
            if second_relation_value:
                vals['second_relation_with_employee'] = second_relation_value

            if self._val(data.get('private_street')):
                vals['private_street'] = self._val(data.get('private_street'))
            if self._val(data.get('private_city')):
                vals['private_city'] = self._val(data.get('private_city'))
            if self._val(data.get('private_zip')):
                vals['private_zip'] = self._val(data.get('private_zip'))
            if self._val(data.get('private_phone')):
                vals['private_phone'] = self._val(data.get('private_phone'))

            relationship_id = self._get_or_create_relationship(data.get('relationship_with_emp_id'))
            if relationship_id:
                vals['relationship_with_emp_id'] = relationship_id

            if self._val(data.get('sex')):
                sex_value = self._val(data.get('sex')).lower()
                if sex_value in ['male', 'female', 'other']:
                    vals['sex'] = sex_value

            if self._val(data.get('marital')):
                marital_value = self._val(data.get('marital')).lower()
                if marital_value in ['single', 'married', 'cohabitant', 'widower', 'divorced']:
                    vals['marital'] = marital_value

            vals.update({
                'birthday': self._parse_date(data.get('birthday')),
                'issue_date': self._parse_date(data.get('issue_date')),
                'passport_expiration_date': self._parse_date(data.get('passport_expiration_date')),
                'leave_date_from': self._parse_date(data.get('leave_date_from')),
                'start_date_of_degree': self._parse_date(data.get('start_date_of_degree')),
                'completion_date_of_degree': self._parse_date(data.get('completion_date_of_degree')),
                'expiry_date': self._parse_date(data.get('expiry_date')),
            })

            try:
                salary = self._val(data.get('last_salary_per_annum_amt'))
                if salary:
                    vals['last_salary_per_annum_amt'] = float(salary)
            except:
                pass

            country = self._find_country(data.get('country_id'))
            if country:
                vals['country_id'] = country.id

            private_country = self._find_country(data.get('private_country_id'))
            if private_country:
                vals['private_country_id'] = private_country.id

            issue_country = self._find_country(data.get('issue_countries_id'))
            if issue_country:
                vals['issue_countries_id'] = issue_country.id

            private_state = self._find_state(data.get('private_state_id'),
                                             private_country.id if private_country else None)
            if private_state:
                vals['private_state_id'] = private_state.id

            mother_tongue = self._find_language_in_res_lang(data.get('mother_tongue_id'))
            if mother_tongue:
                vals['mother_tongue_id'] = mother_tongue.id

            # Languages
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
                for name in lang_names:
                    lang_obj = self._find_language_in_res_lang(name)
                    if lang_obj:
                        language_ids_to_set.append(lang_obj.id)

            # CREATE or UPDATE
            if employee:
                _logger.info(f"🔄 UPDATING: {employee.name} (ID: {employee.id})")
                employee.write(vals)
                action = "updated"
            else:
                _logger.info(f"➕ CREATING new employee")
                employee = Employee.with_context(auto_generate_code=False).create(vals)
                action = "created"

            _logger.info(f"✓ Saved to Odoo:")
            _logger.info(f"   emp_code: '{employee.emp_code}'")
            _logger.info(f"   engagement_location: '{employee.engagement_location}'")
            _logger.info(f"   payroll_location: '{employee.payroll_location}'")
            _logger.info(f"   employment_type: '{employee.employment_type}'")

            # Set languages
            if language_ids_to_set:
                try:
                    employee.write({'language_known_ids': [(6, 0, language_ids_to_set)]})
                    employee.invalidate_cache(['language_known_ids'])
                except Exception as e:
                    _logger.error(f"❌ Language error: {e}")

            response_data = {
                'success': True,
                'action': action,
                'employee_id': employee.id,
                'name': employee.name,
                'email': employee.work_email or '',
                'emp_code': employee.emp_code or '',
                'normalized_fields': {
                    'engagement_location': employee.engagement_location,
                    'payroll_location': employee.payroll_location,
                    'employment_type': employee.employment_type
                }
            }

            _logger.info(f"✅ SUCCESS: {json.dumps(response_data, indent=2)}")
            return self._json_response(response_data)

        except Exception as e:
            _logger.error(f"❌ ERROR: {str(e)}", exc_info=True)
            try:
                request.env.cr.rollback()
            except:
                pass
            return self._json_response({'success': False, 'error': str(e)}, 500)

    def _find_employee(self, name):
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