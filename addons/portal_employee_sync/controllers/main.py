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
                    _logger.info(f"📤 Extracted from SharePoint JSON: {value}")
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

    def _find_language_in_language_master(self, name):
        """
        Search in language_master table for language
        Maps common language names to language_master records
        """
        name = self._val(name)
        if not name:
            _logger.warning(f"⚠️ _find_language_in_language_master called with empty name")
            return None

        name = name.strip()
        _logger.info(f"🔍 Searching for language in language_master: '{name}'")

        try:
            # First: Try exact name match (case insensitive)
            lang = request.env['language_master'].sudo().search([
                ('name', '=ilike', name)
            ], limit=1)
            if lang:
                _logger.info(f"✅ Found by exact name: '{name}' -> ID: {lang.id}, Name: '{lang.name}'")
                return lang

            # Second: Try partial name match
            lang = request.env['language_master'].sudo().search([
                ('name', 'ilike', name)
            ], limit=1)
            if lang:
                _logger.info(f"✅ Found by partial name: '{name}' -> ID: {lang.id}, Name: '{lang.name}'")
                return lang

            # Third: Try common variations
            name_variations = {
                'english': ['English', 'EN', 'eng'],
                'hindi': ['Hindi', 'HI', 'hin'],
                'telugu': ['Telugu', 'TE', 'tel'],
                'tamil': ['Tamil', 'TA', 'tam'],
                'kannada': ['Kannada', 'KN', 'kan'],
                'malayalam': ['Malayalam', 'ML', 'mal'],
                'marathi': ['Marathi', 'MR', 'mar'],
                'bengali': ['Bengali', 'BN', 'ben'],
                'gujarati': ['Gujarati', 'GU', 'guj'],
                'punjabi': ['Punjabi', 'PA', 'pan'],
                'urdu': ['Urdu', 'UR', 'urd'],
                'arabic': ['Arabic', 'AR', 'ara'],
                'french': ['French', 'FR', 'fra'],
                'german': ['German', 'DE', 'deu'],
                'spanish': ['Spanish', 'ES', 'spa'],
                'chinese': ['Chinese', 'ZH', 'chi'],
                'japanese': ['Japanese', 'JA', 'jpn'],
            }

            name_lower = name.lower()
            if name_lower in language_variations:
                for variant in language_variations[name_lower]:
                    lang = request.env['language_master'].sudo().search([
                        ('name', 'ilike', variant)
                    ], limit=1)
                    if lang:
                        _logger.info(f"✅ Found by variant '{variant}': ID: {lang.id}")
                        return lang

            # Log available languages for debugging
            _logger.warning(f"⚠️ Language NOT found: '{name}'")
            all_langs = request.env['language_master'].sudo().search([], limit=15)
            available = [l.name for l in all_langs]
            _logger.info(f"📋 Sample available languages in language_master: {available}")

            return None

        except Exception as e:
            _logger.error(f"❌ Error searching language_master: {e}", exc_info=True)
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
        # CRITICAL: Set admin user context FIRST
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

            # Use request.env (already set to admin user)
            Employee = request.env['hr.employee']
            employee = Employee.search([('name', '=', self._val(data.get('name')))], limit=1)

            # DIAGNOSTIC: Check if field exists
            _logger.info("🔍 DIAGNOSTIC: Checking if 'second_relation_with_employee' field exists")
            try:
                if 'second_relation_with_employee' in Employee._fields:
                    _logger.info("✅ Field 'second_relation_with_employee' EXISTS in hr.employee model")
                    field_info = Employee._fields['second_relation_with_employee']
                    _logger.info(f"   Field type: {field_info.type}, required: {field_info.required}")
                else:
                    _logger.error("❌ Field 'second_relation_with_employee' DOES NOT EXIST in hr.employee model")
            except Exception as e:
                _logger.error(f"❌ Error checking field: {e}")

            # DIAGNOSTIC: Extract and log the value
            second_relation_value = self._val(data.get('second_relation_with_employee'))
            _logger.info(f"📋 DIAGNOSTIC: Extracted second_relation_with_employee value: '{second_relation_value}'")

            # EMPLOYEE VALUES
            vals = {
                'name': self._val(data.get('name')),
                'work_email': self._val(data.get('email')),
                'mobile_phone': self._val(data.get('phone')),
                'emp_code': self._val(data.get('employee_code')),
                'total_it_experience': self._val(data.get('total_it_experience')),
                'alternate_mobile_number': self._val(data.get('alternate_mobile_number')),
                'second_alternative_number': self._val(data.get('second_alternative_number')),
                'engagement_location': self._val(data.get('engagement_location')),
                'payroll_location': self._val(data.get('payroll_location')),
                'employment_type': self._val(data.get('employment_type')),
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

            line_manager = self._find_employee(data.get('line_manager'))

            if line_manager:
                vals['line_manager_id'] = line_manager.id
                _logger.info(f"✅ Line Manager set: {line_manager.name} (ID {line_manager.id})")
            else:
                _logger.info(f"ℹ️ No Line Manager found for: {data.get('line_manager')}")

            # Add second_relation_with_employee conditionally
            if second_relation_value:
                vals['second_relation_with_employee'] = second_relation_value
                _logger.info(f"✅ Added 'second_relation_with_employee' to vals: '{second_relation_value}'")

            emp_code_value = self._val(data.get('employee_code'))  # API sends "employee_code"
            if emp_code_value:
                vals['emp_code'] = emp_code_value  # But we save to "emp_code"
                _logger.info(f"✅ Using employee_code from API: {emp_code_value}")

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

            # MOTHER TONGUE (from language_master)
            _logger.info("🌐 Processing Mother Tongue...")
            mother_tongue = self._find_language_in_language_master(data.get('mother_tongue_id'))
            if mother_tongue:
                vals['mother_tongue_id'] = mother_tongue.id
                _logger.info(f"✅ Mother Tongue set: {mother_tongue.name} (ID: {mother_tongue.id})")
            else:
                mother_tongue_value = self._val(data.get('mother_tongue_id'))
                if mother_tongue_value:
                    _logger.warning(f"⚠️ Mother Tongue '{mother_tongue_value}' not found in language_master")

            # ========== PROCESS LANGUAGES KNOWN (language_master) ==========
            _logger.info("=" * 80)
            _logger.info("🌐 STARTING LANGUAGE PROCESSING (language_master)")
            _logger.info("=" * 80)

            # Try multiple possible field names from SharePoint
            langs_raw_data = (
                    data.get('language_known_ids') or
                    data.get('names') or
                    data.get('languages') or
                    data.get('language_known')
            )

            _logger.info(f"📥 Raw language data from API: {langs_raw_data}")
            _logger.info(f"📋 Type: {type(langs_raw_data)}")

            langs_raw = self._val(langs_raw_data)
            language_ids_to_set = []

            if langs_raw:
                _logger.info(f"✅ Cleaned language value: '{langs_raw}'")

                # Split by comma and process each language
                lang_names = [name.strip() for name in langs_raw.split(',') if name.strip()]
                _logger.info(f"📋 Split into {len(lang_names)} language(s): {lang_names}")

                for idx, name in enumerate(lang_names, 1):
                    _logger.info(f"\n--- Processing language {idx}/{len(lang_names)}: '{name}' ---")

                    lang_obj = self._find_language_in_language_master(name)

                    if lang_obj:
                        language_ids_to_set.append(lang_obj.id)
                        _logger.info(
                            f"✅ SUCCESS: Added language_master ID {lang_obj.id} ('{lang_obj.name}')")
                    else:
                        _logger.error(f"❌ FAILED: Language '{name}' not found in language_master")

                _logger.info(f"\n{'=' * 80}")
                _logger.info(f"📊 LANGUAGE PROCESSING SUMMARY:")
                _logger.info(f"   • Input string: '{langs_raw}'")
                _logger.info(f"   • Languages found: {len(language_ids_to_set)}/{len(lang_names)}")
                _logger.info(f"   • IDs to save: {language_ids_to_set}")
                _logger.info(f"{'=' * 80}\n")
            else:
                _logger.info(f"ℹ️ No languages provided in request")

            # LOG FINAL VALUES
            _logger.info(f"📋 Final vals (before create/update): {json.dumps(vals, default=str, indent=2)}")

            # CREATE OR UPDATE EMPLOYEE
            if employee:
                _logger.info(f"🔄 UPDATING existing employee: {employee.name} (ID: {employee.id})")
                employee.write(vals)
                action = "updated"
                _logger.info(f"✅ Employee UPDATED")
            else:
                _logger.info(f"➕ CREATING new employee")
                employee = Employee.with_context(auto_generate_code=False).create(vals)
                action = "created"
                _logger.info(f"✅ Employee CREATED: {employee.name} (ID: {employee.id})")

            # ========== SET LANGUAGES SEPARATELY (CRITICAL FOR MANY2MANY) ==========
            if language_ids_to_set:
                try:
                    _logger.info(f"\n{'=' * 80}")
                    _logger.info(f"🌐 SETTING LANGUAGES FOR EMPLOYEE {employee.id}")
                    _logger.info(f"{'=' * 80}")
                    _logger.info(f"   Language IDs to set: {language_ids_to_set}")

                    # Clear existing languages first
                    employee.write({
                        'language_known_ids': [(5, 0, 0)]  # (5, 0, 0) = Clear all
                    })
                    _logger.info(f"🗑️ Cleared existing languages")

                    # Now set the new languages
                    employee.write({
                        'language_known_ids': [(6, 0, language_ids_to_set)]  # (6, 0, [IDs]) = Replace with these IDs
                    })
                    _logger.info(f"💾 Languages written to database using ORM write")

                    # Force refresh from database
                    employee.invalidate_cache(['language_known_ids'])

                    # Verify what was actually saved
                    saved_langs = employee.language_known_ids
                    saved_ids = saved_langs.ids
                    saved_names = saved_langs.mapped('name')

                    _logger.info(f"\n{'=' * 80}")
                    _logger.info(f"✅ VERIFICATION RESULTS:")
                    _logger.info(f"   • Expected IDs: {language_ids_to_set}")
                    _logger.info(f"   • Saved IDs: {saved_ids}")
                    _logger.info(f"   • Saved Names: {saved_names}")
                    _logger.info(f"   • Count: {len(saved_ids)}/{len(language_ids_to_set)}")

                    if set(saved_ids) == set(language_ids_to_set):
                        _logger.info(f"🎉 ALL LANGUAGES SAVED SUCCESSFULLY!")
                    else:
                        missing = set(language_ids_to_set) - set(saved_ids)
                        extra = set(saved_ids) - set(language_ids_to_set)
                        if missing:
                            _logger.error(f"❌ Missing IDs: {missing}")
                        if extra:
                            _logger.error(f"⚠️ Extra IDs: {extra}")
                    _logger.info(f"{'=' * 80}\n")

                except Exception as e:
                    _logger.error(f"❌ ERROR SETTING LANGUAGES: {e}", exc_info=True)
            else:
                _logger.info(f"ℹ️ No languages to set for employee {employee.id}")

            # Prepare response
            azure_email = employee.work_email or ''
            azure_id = ''
            if hasattr(employee, 'azure_user_id'):
                azure_id = employee.azure_user_id or ''

            # Get saved languages for response
            saved_language_info = []
            if language_ids_to_set:
                for lang in employee.language_known_ids:
                    saved_language_info.append({
                        'id': lang.id,
                        'name': lang.name
                    })

            response_data = {
                'success': True,
                'action': action,
                'employee_id': employee.id,
                'name': employee.name,
                'email': azure_email,
                'azure_user_id': azure_id,
                'mother_tongue': mother_tongue.name if mother_tongue else None,
                'languages_saved': saved_language_info,
                'languages_count': len(saved_language_info)
            }

            _logger.info(f"📤 Response: {json.dumps(response_data, indent=2)}")

            return self._json_response(response_data)

        except Exception as e:
            _logger.error(f"❌ CRITICAL ERROR: {str(e)}", exc_info=True)
            try:
                request.env.cr.rollback()
            except:
                pass
            return self._json_response({'success': False, 'error': str(e)}, 500)

    def _find_employee(self, name):
        """Find employee by name (for line manager mapping)"""
        name = self._val(name)
        if not name:
            return None

        employee = request.env['hr.employee'].sudo().search([
            ('name', '=ilike', name)
        ], limit=1)

        if employee:
            _logger.info(f"✅ Found Line Manager: {employee.name} (ID {employee.id})")
        else:
            _logger.warning(f"⚠️ Line Manager not found for name: {name}")

        return employee

    def _json_response(self, data, status=200):
        return request.make_response(
            json.dumps(data, indent=2),
            headers=[
                ('Content-Type', 'application/json'),
                ('Access-Control-Allow-Origin', '*'),
            ],
            status=status
        )