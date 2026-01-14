from odoo import http
from odoo.http import request
import json
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class PortalEmployeeSyncController(http.Controller):

    def _verify_api_key(self, api_key):
        """Verify API key"""
        valid_key = "a7cf0c4f99a71e9f63c60fda3aa32c0ecba87669"
        return api_key == valid_key

    def _extract_sharepoint_value(self, field_data, field_name="field"):
        """Extract value from SharePoint field data"""
        if not field_data:
            return None
        if isinstance(field_data, dict):
            value = field_data.get('Value') or field_data.get('value')
            if value:
                return str(value).strip()
            return None
        value = str(field_data).strip()
        return value if value else None

    def _parse_date(self, date_str):
        """Parse date string to Odoo format"""
        if not date_str:
            return None
        try:
            date_str = str(date_str).strip()
            date_formats = [
                '%m/%d/%Y', '%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d', '%d-%m-%Y',
                '%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ',
            ]
            for fmt in date_formats:
                try:
                    date_obj = datetime.strptime(date_str, fmt)
                    return date_obj.strftime('%Y-%m-%d')
                except:
                    continue
        except Exception as e:
            _logger.error(f"Error parsing date: {e}")
        return None

    @http.route('/odoo/api/employees', type='http', auth='none', methods=['POST', 'GET'], csrf=False, cors='*')
    def create_employee(self, **kwargs):
        """Create OR UPDATE employee from SharePoint"""
        try:
            api_key = request.httprequest.headers.get('api-key') or \
                      request.httprequest.headers.get('API-Key') or \
                      request.httprequest.headers.get('Authorization', '').replace('Bearer ', '')

            _logger.info(f"========== NEW EMPLOYEE REQUEST ==========")

            if not api_key or not self._verify_api_key(api_key):
                return self._json_response({'error': 'Invalid API key', 'status': 401}, 401)

            try:
                if request.httprequest.data:
                    data = json.loads(request.httprequest.data.decode('utf-8'))
                else:
                    data = request.httprequest.form.to_dict()
                _logger.info(f"Received data: {json.dumps(data, indent=2)}")
            except Exception as e:
                return self._json_response({'error': f'Invalid JSON: {str(e)}', 'status': 400}, 400)

            if not data.get('name'):
                return self._json_response({'error': 'Name required', 'status': 400}, 400)

            # CHECK IF EMPLOYEE EXISTS
            existing_employee = None
            if data.get('employee_id'):
                existing_employee = request.env['hr.employee'].sudo().search([
                    ('sharepoint_employee_id', '=', str(data.get('employee_id')))
                ], limit=1)

            if not existing_employee and data.get('name'):
                existing_employee = request.env['hr.employee'].sudo().search([
                    ('name', '=', data.get('name'))
                ], limit=1)

            # PREPARE EMPLOYEE DATA
            employee_vals = {'name': data.get('name')}

            if data.get('employee_id'):
                employee_vals['sharepoint_employee_id'] = str(data.get('employee_id'))

            if not existing_employee and data.get('email'):
                employee_vals['work_email'] = data.get('email')

            # BASIC INFO
            if data.get('phone'):
                employee_vals['mobile_phone'] = data.get('phone')
            if data.get('department'):
                employee_vals['department_id'] = self._get_or_create_department(data.get('department'))
            if data.get('job_title'):
                employee_vals['job_id'] = self._get_or_create_job(data.get('job_title'))

            # NAME FIELDS
            if data.get('employee_first_name'):
                employee_vals['employee_first_name'] = data.get('employee_first_name')
            if data.get('employee_middle_name'):
                employee_vals['employee_middle_name'] = data.get('employee_middle_name')
            if data.get('employee_last_name'):
                employee_vals['employee_last_name'] = data.get('employee_last_name')

            # GENDER
            if data.get('sex'):
                gender_raw = self._extract_sharepoint_value(data.get('sex'), 'Gender')
                if gender_raw:
                    gender_mapping = {'male': 'male', 'm': 'male', 'female': 'female', 'f': 'female', 'other': 'other'}
                    mapped_gender = gender_mapping.get(gender_raw.lower())
                    if mapped_gender:
                        employee_vals['sex'] = mapped_gender

            # BIRTHDAY
            if data.get('birthday'):
                parsed_date = self._parse_date(data.get('birthday'))
                if parsed_date:
                    employee_vals['birthday'] = parsed_date

            # PLACE OF BIRTH
            if data.get('place_of_birth'):
                employee_vals['place_of_birth'] = data.get('place_of_birth')

            # MARITAL STATUS
            if data.get('marital'):
                marital_raw = self._extract_sharepoint_value(data.get('marital'), 'Marital')
                if marital_raw:
                    marital_mapping = {
                        'single': 'single', 'unmarried': 'single', 'married': 'married',
                        'cohabitant': 'cohabitant', 'widower': 'widower', 'divorced': 'divorced'
                    }
                    mapped_marital = marital_mapping.get(marital_raw.lower())
                    if mapped_marital:
                        employee_vals['marital'] = mapped_marital

            # PRIVATE EMAIL
            if data.get('private_email'):
                employee_vals['private_email'] = data.get('private_email')

            # LANGUAGES
            if data.get('names'):
                employee_vals['names'] = data.get('names')

            # MOTHER TONGUE
            if data.get('mother_tongue_id'):
                lang_raw = self._extract_sharepoint_value(data.get('mother_tongue_id'), 'Mother Tongue')
                if lang_raw:
                    lang = self._find_language(lang_raw)
                    if lang:
                        employee_vals['mother_tongue_id'] = lang.id

            # NATIONALITY
            if data.get('country_id'):
                country = self._find_country(data.get('country_id'))
                if country:
                    employee_vals['country_id'] = country.id

            # ============================================
            # PERMANENT ADDRESS (from new mapping)
            # ============================================

            # Buildings Name/Flat No (Private Street)
            if data.get('private_street'):
                employee_vals['private_street'] = data.get('private_street')

            # Country (Private Country)
            if data.get('private_country_id'):
                country = self._find_country(data.get('private_country_id'))
                if country:
                    employee_vals['private_country_id'] = country.id

            # State (Private State)
            if data.get('private_state_id'):
                employee_vals['private_state_id'] = data.get('private_state_id')

            # City (Private City)
            if data.get('private_city'):
                employee_vals['private_city'] = data.get('private_city')

            # PO Box / PIN Code (Private Zip)
            if data.get('private_zip'):
                employee_vals['private_zip'] = str(data.get('private_zip'))

            # Contact Number (Private Phone)
            if data.get('private_phone'):
                employee_vals['private_phone'] = data.get('private_phone')

            # PASSPORT DETAILS
            if data.get('passport_id'):
                employee_vals['passport_id'] = str(data.get('passport_id'))
            if data.get('issue_date'):
                parsed_date = self._parse_date(data.get('issue_date'))
                if parsed_date:
                    employee_vals['issue_date'] = parsed_date
            if data.get('issue_countries_id'):
                country = self._find_country(data.get('issue_countries_id'))
                if country:
                    employee_vals['issue_countries_id'] = country.id
            if data.get('passport_expiration_date'):
                parsed_date = self._parse_date(data.get('passport_expiration_date'))
                if parsed_date:
                    employee_vals['passport_expiration_date'] = parsed_date

            # EMERGENCY CONTACT DETAILS
            if data.get('emergency_contact_person_name'):
                employee_vals['emergency_contact_person_name'] = data.get('emergency_contact_person_name')
            if data.get('emergency_contact_person_phone'):
                employee_vals['emergency_contact_person_phone'] = data.get('emergency_contact_person_phone')
            if data.get('relationship_with_emp_id'):
                employee_vals['relationship_with_emp_id'] = data.get('relationship_with_emp_id')
            if data.get('emergency_contact_person_name_1'):
                employee_vals['emergency_contact_person_name_1'] = data.get('emergency_contact_person_name_1')
            if data.get('emergency_contact_person_phone_1'):
                employee_vals['emergency_contact_person_phone_1'] = data.get('emergency_contact_person_phone_1')
            if data.get('relationship_with_emp_id_1'):
                employee_vals['relationship_with_emp_id_1'] = data.get('relationship_with_emp_id_1')

            # PROFESSIONAL DETAILS
            if data.get('primary_skill'):
                employee_vals['primary_skill'] = data.get('primary_skill')
            if data.get('secondary_skill'):
                employee_vals['secondary_skill'] = data.get('secondary_skill')
            if data.get('last_organisation_name'):
                employee_vals['last_organisation_name'] = data.get('last_organisation_name')
            if data.get('current_address'):
                employee_vals['current_address'] = data.get('current_address')
            if data.get('last_salary_per_annum_amt'):
                try:
                    employee_vals['last_salary_per_annum_amt'] = float(data.get('last_salary_per_annum_amt'))
                except:
                    pass
            if data.get('notice_period'):
                employee_vals['notice_period'] = data.get('notice_period')
            if data.get('reason_for_leaving'):
                employee_vals['reason_for_leaving'] = data.get('reason_for_leaving')

            # CURRENT REPORTING MANAGER DETAILS
            if data.get('last_report_manager_name'):
                employee_vals['last_report_manager_name'] = data.get('last_report_manager_name')
            if data.get('last_report_manager_designation'):
                employee_vals['last_report_manager_designation'] = data.get('last_report_manager_designation')
            if data.get('last_report_manager_mail'):
                employee_vals['last_report_manager_mail'] = data.get('last_report_manager_mail')
            if data.get('last_report_manager_mob_no'):
                employee_vals['last_report_manager_mob_no'] = data.get('last_report_manager_mob_no')

            # INDUSTRY REFERENCE DETAILS
            if data.get('industry_ref_name'):
                employee_vals['industry_ref_name'] = data.get('industry_ref_name')
            if data.get('industry_ref_email'):
                employee_vals['industry_ref_email'] = data.get('industry_ref_email')
            if data.get('industry_ref_mob_no'):
                employee_vals['industry_ref_mob_no'] = data.get('industry_ref_mob_no')

            # PROFESSIONAL EXPERIENCE DETAILS
            if data.get('company_name'):
                employee_vals['company_name'] = data.get('company_name')
            if data.get('date_start'):
                parsed_date = self._parse_date(data.get('date_start'))
                if parsed_date:
                    employee_vals['date_start'] = parsed_date
            if data.get('period_in_company'):
                employee_vals['period_in_company'] = data.get('period_in_company')

            # EDUCATION DETAILS
            if data.get('degree_certificate_legal'):
                employee_vals['degree_certificate_legal'] = data.get('degree_certificate_legal')
            if data.get('degree_name'):
                employee_vals['degree_name'] = data.get('degree_name')
            if data.get('institute_name'):
                employee_vals['institute_name'] = data.get('institute_name')
            if data.get('start_date_of_degree'):
                parsed_date = self._parse_date(data.get('start_date_of_degree'))
                if parsed_date:
                    employee_vals['start_date_of_degree'] = parsed_date
            if data.get('completion_date_of_degree'):
                parsed_date = self._parse_date(data.get('completion_date_of_degree'))
                if parsed_date:
                    employee_vals['completion_date_of_degree'] = parsed_date
            if data.get('score'):
                employee_vals['score'] = data.get('score')

            # CREATE OR UPDATE EMPLOYEE
            if existing_employee:
                _logger.info(f"📝 UPDATING existing employee: {existing_employee.name}")
                existing_employee.write(employee_vals)
                employee = existing_employee
            else:
                _logger.info(f"✨ Creating NEW employee")
                employee = request.env['hr.employee'].sudo().create(employee_vals)

            # COMMIT TRANSACTION
            request.env.cr.commit()

            _logger.info(f"✅ Employee {'updated' if existing_employee else 'created'} successfully (ID: {employee.id})")
            _logger.info(f"========== REQUEST COMPLETE ==========\n")

            return self._json_response({
                'success': True,
                'status': 'success',
                'employee_id': employee.id,
                'message': f'Employee {"updated" if existing_employee else "created"} successfully',
                'action': 'update' if existing_employee else 'create',
                'data': {
                    'id': employee.id,
                    'name': employee.name,
                    'email': employee.work_email or '',
                    'sharepoint_id': employee.sharepoint_employee_id or '',
                }
            })

        except Exception as e:
            _logger.error(f"❌ CRITICAL ERROR: {str(e)}", exc_info=True)
            return self._json_response({'error': str(e), 'status': 500}, 500)

    def _find_country(self, country_name):
        """Find country by name"""
        if not country_name:
            return None
        country_name = str(country_name).strip()
        return request.env['res.country'].sudo().search([
            '|', '|',
            ('name', '=ilike', country_name),
            ('name', 'ilike', country_name),
            ('code', '=ilike', country_name)
        ], limit=1)

    def _find_language(self, lang_name):
        """Find language by name"""
        if not lang_name:
            return None
        lang_name = str(lang_name).strip()
        return request.env['res.lang'].sudo().search([
            '|', '|', '|',
            ('name', '=ilike', lang_name),
            ('name', 'ilike', lang_name),
            ('iso_code', '=ilike', lang_name),
            ('code', '=ilike', lang_name)
        ], limit=1)

    def _get_or_create_department(self, dept_name):
        if not dept_name:
            return False
        department = request.env['hr.department'].sudo().search([('name', '=', dept_name)], limit=1)
        if not department:
            department = request.env['hr.department'].sudo().create({'name': dept_name})
        return department.id

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
            headers=[
                ('Content-Type', 'application/json'),
                ('Access-Control-Allow-Origin', '*'),
            ],
            status=status
        )