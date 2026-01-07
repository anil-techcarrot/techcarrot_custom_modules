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

    @http.route('/api/employees', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def create_employee(self, **kwargs):
        """Create OR UPDATE employee from external system"""
        try:
            # Get API key from headers
            api_key = request.httprequest.headers.get('api-key') or \
                      request.httprequest.headers.get('API-Key') or \
                      request.httprequest.headers.get('Authorization', '').replace('Bearer ', '')

            _logger.info(f"========== NEW EMPLOYEE REQUEST ==========")

            if not api_key or not self._verify_api_key(api_key):
                return self._json_response({'error': 'Invalid API key', 'status': 401}, 401)

            # Parse JSON data
            try:
                if request.httprequest.data:
                    data = json.loads(request.httprequest.data.decode('utf-8'))
                else:
                    data = request.httprequest.form.to_dict()
                _logger.info(f"📥 Received data: {json.dumps(data, indent=2)}")
            except Exception as e:
                return self._json_response({'error': f'Invalid JSON: {str(e)}', 'status': 400}, 400)

            if not data.get('name'):
                return self._json_response({'error': 'Name required', 'status': 400}, 400)

            # CHECK IF EMPLOYEE EXISTS
            existing_employee = None

            # Search by Name
            if data.get('name'):
                existing_employee = request.env['hr.employee'].sudo().search([
                    ('name', '=', data.get('name'))
                ], limit=1)
                if existing_employee:
                    _logger.info(f"✅ Found existing employee: {data.get('name')}")

            # Search by first/last name if name search fails
            if not existing_employee and data.get('employee_first_name') and data.get('employee_last_name'):
                existing_employee = request.env['hr.employee'].sudo().search([
                    ('employee_first_name', '=', data.get('employee_first_name')),
                    ('employee_last_name', '=', data.get('employee_last_name'))
                ], limit=1)
                if existing_employee:
                    _logger.info(f"✅ Found by first+last name")

            # BASE EMPLOYEE DATA
            employee_vals = {
                'name': data.get('name'),
                'mobile_phone': data.get('phone'),
                'department_id': self._get_or_create_department(data.get('department')),
                'job_id': self._get_or_create_job(data.get('job_title')),
            }

            # Only set email for NEW employees
            if not existing_employee:
                employee_vals['work_email'] = data.get('email')
                _logger.info(f"📧 Setting email for NEW employee")
            else:
                _logger.info(f"📧 SKIPPING email - employee exists")

            # NAME FIELDS
            if data.get('employee_first_name'):
                employee_vals['employee_first_name'] = data.get('employee_first_name')
            if data.get('employee_middle_name'):
                employee_vals['employee_middle_name'] = data.get('employee_middle_name')
            if data.get('employee_last_name'):
                employee_vals['employee_last_name'] = data.get('employee_last_name')

            # GENDER
            if data.get('sex'):
                gender_value = str(data.get('sex')).lower().strip()
                _logger.info(f"📝 Processing gender: '{gender_value}'")
                gender_mapping = {
                    'male': 'male', 'm': 'male',
                    'female': 'female', 'f': 'female',
                    'other': 'other',
                }
                mapped_gender = gender_mapping.get(gender_value)
                if mapped_gender:
                    employee_vals['sex'] = mapped_gender
                    _logger.info(f"✅ Gender: {mapped_gender}")
            else:
                _logger.warning(f"⚠️ No 'sex' field in data")

            # BIRTHDAY
            if data.get('birthday'):
                try:
                    from datetime import datetime
                    birthday_str = str(data.get('birthday')).strip()
                    _logger.info(f"📝 Processing birthday: '{birthday_str}'")
                    date_obj = None
                    for fmt in ['%m/%d/%Y', '%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d', '%d-%m-%Y']:
                        try:
                            date_obj = datetime.strptime(birthday_str, fmt)
                            break
                        except:
                            continue
                    if date_obj:
                        employee_vals['birthday'] = date_obj.strftime('%Y-%m-%d')
                        _logger.info(f"✅ Birthday: {employee_vals['birthday']}")
                except Exception as e:
                    _logger.error(f"❌ Birthday error: {e}")
            else:
                _logger.warning(f"⚠️ No 'birthday' field in data")

            # PLACE OF BIRTH
            if data.get('place_of_birth'):
                employee_vals['place_of_birth'] = data.get('place_of_birth')

            # MARITAL STATUS
            if data.get('marital'):
                marital_value = str(data.get('marital')).lower().strip()
                _logger.info(f"📝 Processing marital: '{marital_value}'")
                marital_mapping = {
                    'single': 'single', 'unmarried': 'single', 'un married': 'single',
                    'married': 'married',
                    'cohabitant': 'cohabitant', 'living together': 'cohabitant',
                    'widower': 'widower', 'widow': 'widower',
                    'divorced': 'divorced',
                }
                mapped_marital = marital_mapping.get(marital_value)
                if mapped_marital:
                    employee_vals['marital'] = mapped_marital
                    _logger.info(f"✅ Marital: {mapped_marital}")
            else:
                _logger.warning(f"⚠️ No 'marital' field in data")

            # PRIVATE EMAIL
            if data.get('private_email'):
                employee_vals['private_email'] = data.get('private_email')

            # COUNTRY
            if data.get('country_id'):
                country_name = str(data.get('country_id')).strip()
                _logger.info(f"📝 Processing country: '{country_name}'")
                country = request.env['res.country'].sudo().search([
                    '|', '|',
                    ('name', '=ilike', country_name),
                    ('name', 'ilike', country_name),
                    ('code', '=ilike', country_name)
                ], limit=1)
                if country:
                    employee_vals['country_id'] = country.id
                    _logger.info(f"✅ Country: {country.name}")
                else:
                    _logger.warning(f"⚠️ Country not found: '{country_name}'")
            else:
                _logger.warning(f"⚠️ No 'country_id' field in data")

            # MOTHER TONGUE
            if data.get('mother_tongue_id'):
                lang_name = str(data.get('mother_tongue_id')).strip()
                _logger.info(f"📝 Processing mother tongue: '{lang_name}'")
                lang = request.env['res.lang'].sudo().search([
                    '|', '|', '|',
                    ('name', '=ilike', lang_name),
                    ('name', 'ilike', lang_name),
                    ('iso_code', '=ilike', lang_name),
                    ('code', '=ilike', lang_name)
                ], limit=1)
                if lang:
                    employee_vals['mother_tongue_id'] = lang.id
                    _logger.info(f"✅ Mother tongue: {lang.name}")
                else:
                    _logger.warning(f"⚠️ Language '{lang_name}' not found in Odoo")
            else:
                _logger.warning(f"⚠️ No 'mother_tongue_id' field in data")

            # LANGUAGES KNOWN
            if data.get('language_known_ids'):
                try:
                    lang_string = str(data.get('language_known_ids')).strip()
                    _logger.info(f"📝 Processing languages: '{lang_string}'")
                    lang_names = [l.strip() for l in lang_string.split(',') if l.strip()]
                    if lang_names:
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
                            _logger.info(f"✅ Languages: {', '.join(found_langs.mapped('name'))}")
                except Exception as e:
                    _logger.error(f"❌ Languages error: {e}")
            else:
                _logger.warning(f"⚠️ No 'language_known_ids' field in data")

            # CREATE OR UPDATE
            if existing_employee:
                _logger.info(f"📝 UPDATING: {existing_employee.name}")
                existing_employee.write(employee_vals)
                employee = existing_employee
            else:
                _logger.info(f"🆕 CREATING new employee")
                employee = request.env['hr.employee'].sudo().create(employee_vals)

            _logger.info(f"✅ SUCCESS: {employee.name} (ID: {employee.id})")
            _logger.info(f"========== COMPLETE ==========\n")

            return self._json_response({
                'success': True,
                'employee_id': employee.id,
                'message': f'Employee {"updated" if existing_employee else "created"}',
                'data': {
                    'id': employee.id,
                    'name': employee.name,
                    'email': employee.work_email or '',
                    'gender': employee.sex or '',
                    'marital': employee.marital or '',
                    'mother_tongue': employee.mother_tongue_id.name if employee.mother_tongue_id else '',
                    'languages_known': ', '.join(employee.language_known_ids.mapped('name')) if employee.language_known_ids else '',
                }
            })

        except Exception as e:
            _logger.error(f"❌ ERROR: {str(e)}", exc_info=True)
            return self._json_response({'error': str(e), 'status': 500}, 500)

    def _get_or_create_department(self, dept_name):
        if not dept_name:
            return False
        dept = request.env['hr.department'].sudo().search([('name', '=', dept_name)], limit=1)
        if not dept:
            dept = request.env['hr.department'].sudo().create({'name': dept_name})
        return dept.id

    def _get_or_create_job(self, job_title):
        if not job_title:
            return False
        job = request.env['hr.job'].sudo().search([('name', '=', job_title)], limit=1)
        if not job:
            job = request.env['hr.job'].sudo().create({'name': job_title})
        return job.id

    def _json_response(self, data, status=200):
        return request.make_response(
            json.dumps(data, indent=2),
            headers=[('Content-Type', 'application/json'), ('Access-Control-Allow-Origin', '*')],
            status=status
        )