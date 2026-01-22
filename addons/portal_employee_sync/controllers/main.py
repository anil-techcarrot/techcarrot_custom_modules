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
                # Check if it's a JSON string that needs parsing
                if '"Value"' in value or '"value"' in value:
                    parsed = json.loads(value)
                    value = parsed.get('Value') or parsed.get('value')
                    _logger.info(f" Extracted from SharePoint JSON: {value}")
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

    def _find_language(self, name):
        """Search in language.master table with exact match priority"""
        name = self._val(name)
        if not name:
            return None

        name = name.strip()

        try:
            # First: Try EXACT match (case insensitive)
            lang = request.env['language.master'].sudo().search([
                ('name', '=ilike', name)
            ], limit=1)
            if lang:
                _logger.info(f" Found language (exact): {name} -> ID: {lang.id}")
                return lang

            # Second: Try partial match
            lang = request.env['language.master'].sudo().search([
                ('name', 'ilike', name)
            ], limit=1)
            if lang:
                _logger.info(f" Found language (partial): {name} -> ID: {lang.id}")
                return lang

            _logger.warning(f" Language NOT found in language.master: {name}")
            return None

        except Exception as e:
            _logger.error(f" Error searching language.master: {e}")
            # Fallback to res.lang
            _logger.warning(f"Trying res.lang as fallback for: {name}")
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
        # CRITICAL: Set admin user context FIRST
        admin_user = request.env.ref('base.user_admin')
        request.update_env(user=admin_user.id)

        try:
            api_key = request.httprequest.headers.get('api-key')
            if not self._verify_api_key(api_key):
                return self._json_response({'success': False, 'error': 'Invalid API key'}, 401)

            data = json.loads(request.httprequest.data or "{}")
            _logger.info(f" Received: {json.dumps(data, indent=2)}")

            if not self._val(data.get('name')):
                return self._json_response({'success': False, 'error': 'Name is required'}, 400)

            # Use request.env (already set to admin user)
            Employee = request.env['hr.employee']
            employee = Employee.search([('name', '=', self._val(data.get('name')))], limit=1)



            # EMPLOYEE VALUES
            vals = {
                'name': self._val(data.get('name')),
                'work_email': self._val(data.get('email')),
                'mobile_phone': self._val(data.get('phone')),
                'employee_code': self._val(data.get('employee_code')),
                'total_it_experience': self._val(data.get('total_it_experience')),
                'alternate_mobile_number': self._val(data.get('alternate_mobile_number')),
                'second_alternative_number': self._val(data.get('second_alternative_number')),
                'engagement_location': self._val(data.get('engagement_location')),
                'payroll_location': self._val(data.get('payroll_location')),
                'employment_type': self._val(data.get('employment_type')),
                # 'language_known_ids' : self._val(data.get('language_known_ids')),
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


            employee_code_value = self._val(data.get('employee_code'))
            if employee_code_value:
                vals['employee_code'] = employee_code_value
                _logger.info(f"✓ Using employee_code from API: {employee_code_value}")



            # PRIVATE ADDRESS FIELDS
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




            # LANGUAGES KNOWN
          #modify from here to
            # PROCESS LANGUAGES KNOWN (collect IDs but don't add to vals yet)
            langs_raw_data = data.get('names') or data.get('language_known_ids')
            _logger.info(f"🔍 Processing languages from API: {langs_raw_data}")

            langs_raw = self._val(langs_raw_data)
            language_ids_to_set = []  # Store IDs for later use

            if langs_raw:
                _logger.info(f"✓ Languages raw value: '{langs_raw}'")

                # Split by comma for multiple languages
                for name in langs_raw.split(','):
                    name = name.strip()
                    if name:
                        _logger.info(f"🔍 Searching for language: '{name}'")
                        lang_obj = self._find_language(name)
                        if lang_obj:
                            language_ids_to_set.append(lang_obj.id)
                            _logger.info(f"✅ Added language ID: {lang_obj.id} ({lang_obj.name})")
                        else:
                            _logger.warning(f"❌ Language not found: {name}")

                _logger.info(f"📋 Total language IDs collected: {language_ids_to_set}")
            else:
                _logger.info(f"ℹ️ No languages provided")

                 # here is the end to modify

            # LOG FINAL VALUES
            _logger.info(f" Final vals: {json.dumps(vals, default=str, indent=2)}")

            # CREATE OR UPDATE
             # as well modify from here to
            if employee:
                employee.write(vals)
                action = "updated"
                _logger.info(f"✅ UPDATED employee: {employee.name} (ID: {employee.id})")
            else:
                # Disable auto-generation of employee_code when coming from API
                employee = Employee.with_context(auto_generate_code=False).create(vals)
                action = "created"
                _logger.info(f"✅ CREATED employee: {employee.name} (ID: {employee.id})")

            # ===== NOW SET LANGUAGES KNOWN SEPARATELY (CRITICAL FIX) =====
            if language_ids_to_set:
                try:
                    _logger.info(f"🔧 Setting language_known_ids separately for employee {employee.id}")
                    _logger.info(f"   Language IDs to set: {language_ids_to_set}")

                    # Direct SQL insert (most reliable method)
                    request.env.cr.execute(
                        "DELETE FROM hr_employee_language_master_rel WHERE hr_employee_id = %s",
                        (employee.id,)
                    )
                    _logger.info(f"   Cleared existing language relationships")

                    for lang_id in language_ids_to_set:
                        request.env.cr.execute(
                            "INSERT INTO hr_employee_language_master_rel (hr_employee_id, language_master_id) VALUES (%s, %s)",
                            (employee.id, lang_id)
                        )
                    _logger.info(f"   Inserted {len(language_ids_to_set)} language relationships via SQL")

                    # Verify what was saved
                    request.env.cr.execute(
                        "SELECT language_master_id FROM hr_employee_language_master_rel WHERE hr_employee_id = %s",
                        (employee.id,)
                    )
                    saved_ids = [row[0] for row in request.env.cr.fetchall()]
                    _logger.info(f"✅ VERIFICATION: Language IDs in DB: {saved_ids}")

                    if set(saved_ids) == set(language_ids_to_set):
                        _logger.info(f"✅✅ Languages saved successfully!")
                    else:
                        _logger.error(f"❌ Mismatch! Expected {language_ids_to_set}, got {saved_ids}")

                except Exception as e:
                    _logger.error(f"❌ Error setting languages via SQL: {e}", exc_info=True)
            else:
                _logger.info(f"ℹ️ No languages to set for employee {employee.id}")

                # over here to end to modify
            # ===== END LANGUAGE FIX =====




            # ===== END VERIFICATION =====

            # Get Azure details if available
            azure_email = employee.work_email or ''
            azure_id = ''
            if hasattr(employee, 'azure_user_id'):
                azure_id = employee.azure_user_id or ''




            # Return response immediately - Odoo will auto-commit
            return self._json_response({
                'success': True,
                'action': action,
                'employee_id': employee.id,
                'name': employee.name,
                'email': azure_email,
                'azure_user_id': azure_id
            })

        except Exception as e:
            _logger.error(f" ERROR: {str(e)}", exc_info=True)
            try:
                request.env.cr.rollback()
            except:
                pass
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