from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)


class PortalEmployeeSyncController(http.Controller):

    def _verify_api_key(self, api_key):
        """Verify API key"""
        valid_key = "d7ce6e48fe7b6dd95283f5c36f6dd791aa83cf65"
        return api_key == valid_key

    def _extract_sharepoint_value(self, field_data):
        """Extract 'Value' from SharePoint JSON object if present"""
        if not field_data:
            return None

        # Handle empty strings
        if field_data == '':
            return None

        # If it's already a simple string/value, check if it's JSON
        if isinstance(field_data, str):
            field_data = field_data.strip()

            # Check if it's a JSON string containing "Value"
            if field_data.startswith('{') and '"Value"' in field_data:
                try:
                    parsed = json.loads(field_data)
                    value = parsed.get('Value', field_data)
                    # Return None if Value is empty string
                    return value if value != '' else None
                except:
                    return field_data
            return field_data if field_data != '' else None

        # If it's a dict, extract Value
        if isinstance(field_data, dict):
            value = field_data.get('Value', field_data)
            return value if value != '' else None

        return field_data

    def _find_existing_employee(self, data):
        """
        Find existing employee using multiple criteria to prevent duplicates
        Returns existing employee or False
        """
        _logger.info(f"🔍 Searching for existing employee...")

        # Strategy 1: Search by email (most reliable if provided)
        if data.get('email'):
            employee = request.env['hr.employee'].sudo().search([
                ('work_email', '=', data.get('email'))
            ], limit=1)
            if employee:
                _logger.info(f"✅ Found by email: {employee.name} (ID: {employee.id})")
                return employee

        # Strategy 2: Search by exact name match
        if data.get('name'):
            employee = request.env['hr.employee'].sudo().search([
                ('name', '=', data.get('name'))
            ], limit=1)
            if employee:
                _logger.info(f"✅ Found by name: {employee.name} (ID: {employee.id})")
                return employee

        # Strategy 3: Search by first + last name (if provided)
        if data.get('employee_first_name') and data.get('employee_last_name'):
            employee = request.env['hr.employee'].sudo().search([
                ('employee_first_name', '=', data.get('employee_first_name')),
                ('employee_last_name', '=', data.get('employee_last_name'))
            ], limit=1)
            if employee:
                _logger.info(f"✅ Found by first+last name: {employee.name} (ID: {employee.id})")
                return employee

        _logger.info(f"❌ No existing employee found - will create new")
        return False

    @http.route('/api/employees', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def create_employee(self, **kwargs):
        """Create or update employee from external system with all SharePoint fields"""
        try:
            # Get API key from headers
            api_key = request.httprequest.headers.get('api-key') or \
                      request.httprequest.headers.get('API-Key') or \
                      request.httprequest.headers.get('Authorization', '').replace('Bearer ', '')

            _logger.info(f"========== NEW EMPLOYEE REQUEST ==========")
            _logger.info(f"Received API Key: {api_key}")

            if not api_key or not self._verify_api_key(api_key):
                return self._json_response({
                    'error': 'Invalid API key',
                    'status': 401
                }, 401)

            # Parse JSON data from request body
            try:
                if request.httprequest.data:
                    data = json.loads(request.httprequest.data.decode('utf-8'))
                else:
                    data = request.httprequest.form.to_dict()

                _logger.info(f"📥 Received RAW data: {json.dumps(data, indent=2)}")
            except Exception as e:
                return self._json_response({
                    'error': f'Invalid JSON: {str(e)}',
                    'status': 400
                }, 400)

            # Validate required field
            if not data.get('name'):
                return self._json_response({
                    'error': 'Name required',
                    'status': 400
                }, 400)

            # ═══════════════════════════════════════════════════════════
            # FIND EXISTING EMPLOYEE (IMPROVED LOGIC)
            # ═══════════════════════════════════════════════════════════
            existing_employee = self._find_existing_employee(data)

            if existing_employee:
                _logger.info(f"📝 Employee EXISTS: {existing_employee.name} (ID: {existing_employee.id})")
                _logger.info(f"🔄 MODE: UPDATE")
                is_update = True
                employee = existing_employee
            else:
                _logger.info(f"✨ New employee detected")
                _logger.info(f"🆕 MODE: CREATE")
                is_update = False
                employee = None

            # ═══════════════════════════════════════════════════════════
            # BUILD EMPLOYEE VALUES
            # ═══════════════════════════════════════════════════════════
            employee_vals = {}

            # BASIC FIELDS - Always update these
            if data.get('name'):
                employee_vals['name'] = data.get('name')

            if data.get('email'):
                employee_vals['work_email'] = data.get('email')

            if data.get('phone'):
                employee_vals['mobile_phone'] = data.get('phone')

            # Department
            dept_id = self._get_or_create_department(data.get('department'))
            if dept_id:
                employee_vals['department_id'] = dept_id

            # Job Title
            job_id = self._get_or_create_job(data.get('job_title'))
            if job_id:
                employee_vals['job_id'] = job_id

            # NAME FIELDS
            if data.get('employee_first_name'):
                employee_vals['employee_first_name'] = data.get('employee_first_name')
                _logger.info(f"✓ First Name: {data.get('employee_first_name')}")

            if data.get('employee_middle_name'):
                employee_vals['employee_middle_name'] = data.get('employee_middle_name')
                _logger.info(f"✓ Middle Name: {data.get('employee_middle_name')}")

            if data.get('employee_last_name'):
                employee_vals['employee_last_name'] = data.get('employee_last_name')
                _logger.info(f"✓ Last Name: {data.get('employee_last_name')}")

            # ═══════════════════════════════════════════════════════════
            # GENDER - WITH SHAREPOINT JSON EXTRACTION
            # ═══════════════════════════════════════════════════════════
            if data.get('sex'):
                gender_raw = self._extract_sharepoint_value(data.get('sex'))
                _logger.info(f"📝 Gender RAW: '{data.get('sex')}'")
                _logger.info(f"📝 Gender EXTRACTED: '{gender_raw}'")

                if gender_raw:
                    gender_value = str(gender_raw).lower().strip()
                    _logger.info(f"📝 Gender PROCESSED: '{gender_value}'")

                    gender_mapping = {
                        'male': 'male',
                        'm': 'male',
                        'female': 'female',
                        'f': 'female',
                        'other': 'other',
                    }

                    mapped_gender = gender_mapping.get(gender_value)
                    if mapped_gender:
                        employee_vals['gender'] = mapped_gender
                        _logger.info(f"✅ Gender will be set to: {mapped_gender}")
                    else:
                        _logger.warning(f"⚠️ Invalid gender: '{gender_value}'")

            # ═══════════════════════════════════════════════════════════
            # BIRTHDAY - MULTIPLE FORMAT SUPPORT
            # ═══════════════════════════════════════════════════════════
            if data.get('birthday'):
                try:
                    from datetime import datetime
                    birthday_str = str(data.get('birthday')).strip()
                    _logger.info(f"📝 Processing birthday: '{birthday_str}'")

                    date_obj = None
                    date_formats = [
                        '%m/%d/%Y',  # 01/15/1990
                        '%Y-%m-%d',  # 1990-01-15
                        '%d/%m/%Y',  # 15/01/1990
                        '%Y/%m/%d',  # 1990/01/15
                        '%d-%m-%Y',  # 15-01-1990
                    ]

                    for fmt in date_formats:
                        try:
                            date_obj = datetime.strptime(birthday_str, fmt)
                            break
                        except:
                            continue

                    if date_obj:
                        employee_vals['birthday'] = date_obj.strftime('%Y-%m-%d')
                        _logger.info(f"✅ Birthday will be set to: {employee_vals['birthday']}")
                    else:
                        _logger.warning(f"⚠️ Could not parse birthday: '{birthday_str}'")

                except Exception as e:
                    _logger.error(f"❌ Error processing birthday: {e}")

            # PLACE OF BIRTH
            if data.get('place_of_birth'):
                employee_vals['place_of_birth'] = data.get('place_of_birth')
                _logger.info(f"✓ Place of birth: {data.get('place_of_birth')}")

            # ═══════════════════════════════════════════════════════════
            # MARITAL STATUS - WITH SHAREPOINT JSON EXTRACTION
            # ═══════════════════════════════════════════════════════════
            if data.get('marital'):
                marital_raw = self._extract_sharepoint_value(data.get('marital'))
                _logger.info(f"📝 Marital RAW: '{data.get('marital')}'")
                _logger.info(f"📝 Marital EXTRACTED: '{marital_raw}'")

                if marital_raw:
                    marital_value = str(marital_raw).lower().strip()
                    _logger.info(f"📝 Marital PROCESSED: '{marital_value}'")

                    marital_mapping = {
                        'single': 'single',
                        'unmarried': 'single',
                        'un married': 'single',
                        'married': 'married',
                        'cohabitant': 'cohabitant',
                        'living together': 'cohabitant',
                        'widower': 'widower',
                        'widow': 'widower',
                        'divorced': 'divorced',
                    }

                    mapped_marital = marital_mapping.get(marital_value)
                    if mapped_marital:
                        employee_vals['marital'] = mapped_marital
                        _logger.info(f"✅ Marital will be set to: {mapped_marital}")
                    else:
                        _logger.warning(f"⚠️ Invalid marital status: '{marital_value}'")

            # PRIVATE EMAIL
            if data.get('private_email'):
                employee_vals['private_email'] = data.get('private_email')
                _logger.info(f"✓ Private email: {data.get('private_email')}")

            # ═══════════════════════════════════════════════════════════
            # NATIONALITY (COUNTRY) - WITH SHAREPOINT JSON EXTRACTION
            # ═══════════════════════════════════════════════════════════
            if data.get('country_id'):
                country_raw = self._extract_sharepoint_value(data.get('country_id'))
                _logger.info(f"📝 Country RAW: '{data.get('country_id')}'")
                _logger.info(f"📝 Country EXTRACTED: '{country_raw}'")

                if country_raw:
                    country_name = str(country_raw).strip()
                    _logger.info(f"📝 Country PROCESSED: '{country_name}'")

                    # Map nationality variations to country names
                    nationality_to_country = {
                        'indian': 'India',
                        'american': 'United States',
                        'british': 'United Kingdom',
                        'emirati': 'United Arab Emirates',
                        'pakistani': 'Pakistan',
                        'bangladeshi': 'Bangladesh',
                        'sri lankan': 'Sri Lanka',
                        'nepali': 'Nepal',
                        'filipino': 'Philippines',
                    }

                    # Check if it's a nationality that needs mapping
                    mapped_country = nationality_to_country.get(country_name.lower())
                    if mapped_country:
                        country_name = mapped_country
                        _logger.info(f"📍 Mapped nationality to country: {country_name}")

                    # Try EXACT match first
                    country = request.env['res.country'].sudo().search([
                        ('name', '=', country_name)
                    ], limit=1)

                    # If not found, try case-insensitive search
                    if not country:
                        country = request.env['res.country'].sudo().search([
                            '|',
                            ('name', 'ilike', country_name),
                            ('code', '=ilike', country_name)
                        ], limit=1)

                    if country:
                        employee_vals['country_id'] = country.id
                        _logger.info(f"✅ Country will be set to: {country.name} (ID: {country.id})")
                    else:
                        _logger.warning(f"⚠️ Country not found: '{country_name}'")

            # ═══════════════════════════════════════════════════════════
            # MOTHER TONGUE - WITH SHAREPOINT JSON EXTRACTION
            # ═══════════════════════════════════════════════════════════
            if data.get('mother_tongue_id'):
                lang_raw = self._extract_sharepoint_value(data.get('mother_tongue_id'))
                _logger.info(f"📝 Mother Tongue RAW: '{data.get('mother_tongue_id')}'")
                _logger.info(f"📝 Mother Tongue EXTRACTED: '{lang_raw}'")

                if lang_raw:
                    lang_name = str(lang_raw).strip()
                    _logger.info(f"📝 Mother Tongue PROCESSED: '{lang_name}'")

                    # Try multiple search patterns
                    lang = request.env['res.lang'].sudo().search([
                        '|', '|', '|',
                        ('name', '=ilike', lang_name),
                        ('name', 'ilike', lang_name),
                        ('iso_code', '=ilike', lang_name),
                        ('code', '=ilike', lang_name)
                    ], limit=1)

                    if lang:
                        employee_vals['mother_tongue_id'] = lang.id
                        _logger.info(f"✅ Mother tongue will be set to: {lang.name} (ID: {lang.id})")
                    else:
                        _logger.warning(f"⚠️ Language '{lang_name}' not found in Odoo")

            # ═══════════════════════════════════════════════════════════
            # LANGUAGES KNOWN - WITH SHAREPOINT JSON EXTRACTION
            # ═══════════════════════════════════════════════════════════
            if data.get('language_known_ids'):
                try:
                    lang_raw = self._extract_sharepoint_value(data.get('language_known_ids'))
                    _logger.info(f"📝 Languages RAW: '{data.get('language_known_ids')}'")
                    _logger.info(f"📝 Languages EXTRACTED: '{lang_raw}'")

                    if lang_raw:
                        lang_string = str(lang_raw).strip()
                        _logger.info(f"📝 Languages PROCESSED: '{lang_string}'")

                        # Split by comma and clean
                        lang_names = [l.strip() for l in lang_string.split(',') if l.strip()]
                        _logger.info(f"📋 Split into: {lang_names}")

                        if lang_names:
                            # Search for each language
                            found_langs = request.env['res.lang'].sudo()

                            for lang_name in lang_names:
                                lang = request.env['res.lang'].sudo().search([
                                    '|', '|', '|',
                                    ('name', '=ilike', lang_name),
                                    ('name', 'ilike', lang_name),
                                    ('iso_code', '=ilike', lang_name),
                                    ('code', '=ilike', lang_name)
                                ], limit=1)

                                if lang:
                                    found_langs |= lang
                                    _logger.info(f"  ✓ Found: {lang.name}")
                                else:
                                    _logger.warning(f"  ✗ Not found: {lang_name}")

                            if found_langs:
                                employee_vals['language_known_ids'] = [(6, 0, found_langs.ids)]
                                _logger.info(f"✅ Languages will be set: {', '.join(found_langs.mapped('name'))}")
                            else:
                                _logger.warning(f"⚠️ No languages found from: {lang_names}")

                except Exception as e:
                    _logger.error(f"❌ Error processing languages: {e}")

            # ═══════════════════════════════════════════════════════════
            # CREATE OR UPDATE EMPLOYEE
            # ═══════════════════════════════════════════════════════════
            _logger.info(f"📦 Final employee values: {json.dumps(employee_vals, default=str, indent=2)}")

            if is_update:
                # UPDATE existing employee
                _logger.info(f"🔄 UPDATING employee: {employee.name} (ID: {employee.id})")
                _logger.info(f"📝 Old values before update:")
                _logger.info(f"   - Gender: {employee.gender}")
                _logger.info(f"   - Marital: {employee.marital}")
                _logger.info(f"   - Department: {employee.department_id.name if employee.department_id else 'None'}")

                employee.sudo().write(employee_vals)

                _logger.info(f"📝 New values after update:")
                _logger.info(f"   - Gender: {employee.gender}")
                _logger.info(f"   - Marital: {employee.marital}")
                _logger.info(f"   - Department: {employee.department_id.name if employee.department_id else 'None'}")
                _logger.info(f"✅ Employee UPDATED successfully: {employee.name} (ID: {employee.id})")

                message = 'Employee updated successfully'
                status = 'updated'
            else:
                # CREATE new employee
                _logger.info(f"🆕 CREATING new employee")
                employee = request.env['hr.employee'].sudo().create(employee_vals)
                _logger.info(f"✅ Employee CREATED successfully: {employee.name} (ID: {employee.id})")
                message = 'Employee created successfully'
                status = 'created'

            _logger.info(f"========== REQUEST COMPLETE ==========\n")

            # RETURN DETAILED RESPONSE
            return self._json_response({
                'success': True,
                'status': status,
                'employee_id': employee.id,
                'message': message,
                'data': {
                    'id': employee.id,
                    'name': employee.name,
                    'email': employee.work_email or '',
                    'phone': employee.mobile_phone or '',
                    'first_name': employee.employee_first_name or '',
                    'middle_name': employee.employee_middle_name or '',
                    'last_name': employee.employee_last_name or '',
                    'department': employee.department_id.name if employee.department_id else '',
                    'job_title': employee.job_id.name if employee.job_id else '',
                    'gender': employee.gender or '',
                    'birthday': employee.birthday.strftime('%Y-%m-%d') if employee.birthday else '',
                    'place_of_birth': employee.place_of_birth or '',
                    'marital': employee.marital or '',
                    'private_email': employee.private_email or '',
                    'country': employee.country_id.name if employee.country_id else '',
                    'mother_tongue': employee.mother_tongue_id.name if employee.mother_tongue_id else '',
                    'languages_known': ', '.join(
                        employee.language_known_ids.mapped('name')) if employee.language_known_ids else '',
                }
            })

        except Exception as e:
            _logger.error(f"❌ Error creating/updating employee: {str(e)}", exc_info=True)
            return self._json_response({
                'error': str(e),
                'status': 500
            }, 500)

    @http.route('/api/employees', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_employees(self, **kwargs):
        """Get all employees"""
        try:
            # Get API key from headers
            api_key = request.httprequest.headers.get('api-key') or \
                      request.httprequest.headers.get('API-Key') or \
                      request.httprequest.headers.get('Authorization', '').replace('Bearer ', '')

            if not api_key or not self._verify_api_key(api_key):
                return self._json_response({
                    'error': 'Invalid API key',
                    'status': 401
                }, 401)

            # Get all employees
            employees = request.env['hr.employee'].sudo().search([])

            employee_list = []
            for emp in employees:
                employee_list.append({
                    'id': emp.id,
                    'name': emp.name,
                    'email': emp.work_email or '',
                    'phone': emp.mobile_phone or '',
                    'first_name': emp.employee_first_name or '',
                    'middle_name': emp.employee_middle_name or '',
                    'last_name': emp.employee_last_name or '',
                    'department': emp.department_id.name if emp.department_id else '',
                    'job_title': emp.job_id.name if emp.job_id else '',
                    'gender': emp.gender or '',
                    'marital': emp.marital or '',
                    'mother_tongue': emp.mother_tongue_id.name if emp.mother_tongue_id else '',
                    'languages_known': ', '.join(
                        emp.language_known_ids.mapped('name')) if emp.language_known_ids else '',
                })

            return self._json_response({
                'success': True,
                'status': 'success',
                'count': len(employee_list),
                'employees': employee_list
            })

        except Exception as e:
            _logger.error(f"Error fetching employees: {str(e)}")
            return self._json_response({
                'error': str(e),
                'status': 500
            }, 500)

    def _get_or_create_department(self, dept_name):
        """Get or create department"""
        if not dept_name:
            return False

        department = request.env['hr.department'].sudo().search([
            ('name', '=', dept_name)
        ], limit=1)

        if not department:
            department = request.env['hr.department'].sudo().create({
                'name': dept_name
            })
            _logger.info(f"Created new department: {dept_name}")

        return department.id

    def _get_or_create_job(self, job_title):
        """Get or create job position"""
        if not job_title:
            return False

        job = request.env['hr.job'].sudo().search([
            ('name', '=', job_title)
        ], limit=1)

        if not job:
            job = request.env['hr.job'].sudo().create({
                'name': job_title
            })
            _logger.info(f"Created new job: {job_title}")

        return job.id

    def _json_response(self, data, status=200):
        """Return JSON response with proper headers"""
        return request.make_response(
            json.dumps(data, indent=2),
            headers=[
                ('Content-Type', 'application/json'),
                ('Access-Control-Allow-Origin', '*'),
            ],
            status=status
        )