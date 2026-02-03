import requests
import json
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HREmployee(models.Model):
    _inherit = 'hr.employee'

    azure_email = fields.Char("Azure Email", readonly=True)
    azure_user_id = fields.Char("Azure User ID", readonly=True)
    azure_license_assigned = fields.Boolean("License Assigned", default=False, readonly=True)
    azure_license_name = fields.Char("License Name", readonly=True)

    employee_first_name = fields.Char("First Name")
    employee_middle_name = fields.Char("Middle Name")
    employee_last_name = fields.Char("Last Name")
    place_of_birth = fields.Char("Place of Birth")
    mother_tongue_id = fields.Many2one('res.lang', string="Mother Tongue")
    language_known_ids = fields.Many2many(
        'res.lang',
        'employee_language_rel',
        'employee_id',
        'lang_id',
        string="Languages Known"
    )

    total_it_experience = fields.Char("Total IT Experience")
    alternate_mobile_number = fields.Char("Alternate Mobile Number")
    second_alternative_number = fields.Char("Second Alternative Number")

    @api.model_create_multi
    def create(self, vals_list):
        """Automatically runs when employee is created"""

        _logger.info(f"{'=' * 80}")
        _logger.info(f"🔵 CREATE METHOD CALLED - Processing {len(vals_list)} employee(s)")
        _logger.info(f"{'=' * 80}")

        # Remove work_email from vals if provided
        for vals in vals_list:
            if 'work_email' in vals:
                _logger.warning(f"⚠️ work_email provided, removing it - will auto-generate")
                del vals['work_email']

        employees = super().create(vals_list)

        for emp in employees:
            _logger.info(f"🔄 Post-create processing for: {emp.name} (ID: {emp.id})")

            if emp.name:
                _logger.info(f"📧 Calling _create_azure_email() for {emp.name}")
                emp._create_azure_email()

                emp.invalidate_recordset(['work_email', 'azure_email', 'azure_user_id'])

                _logger.info(f"✅ After Azure creation:")
                _logger.info(f"   work_email: {emp.work_email}")
                _logger.info(f"   azure_email: {emp.azure_email}")
                _logger.info(f"   azure_user_id: {emp.azure_user_id}")

                if emp.department_id and emp.azure_user_id:
                    emp._sync_dept_and_add_to_dl()

        _logger.info(f"{'=' * 80}")
        _logger.info(f"✅ CREATE METHOD COMPLETED")
        _logger.info(f"{'=' * 80}")

        return employees

    def write(self, vals):
        """Monitor department changes and validate email changes"""
        if 'work_email' in vals and vals['work_email']:
            for emp in self:
                emp._validate_work_email(vals['work_email'], exclude_id=emp.id)

        result = super().write(vals)

        if 'department_id' in vals:
            for emp in self:
                if emp.azure_user_id and emp.department_id:
                    emp._sync_dept_and_add_to_dl()

        return result

    def _validate_work_email(self, email, exclude_id=None):
        """Validate that work_email doesn't already exist"""
        if not email:
            return

        domain = [('work_email', '=', email.strip().lower())]
        if exclude_id:
            domain.append(('id', '!=', exclude_id))

        existing = self.env['hr.employee'].search(domain, limit=1)

        if existing:
            raise UserError(
                f"⚠️ Email Already Exists!\n\n"
                f"The email '{email}' is already assigned to:\n"
                f"  • Employee: {existing.name}\n"
                f"  • Department: {existing.department_id.name if existing.department_id else 'N/A'}\n"
                f"  • Job Position: {existing.job_id.name if existing.job_id else 'N/A'}\n\n"
                f"Please use a different email address."
            )

    def _sync_dept_and_add_to_dl(self):
        """Sync department DL if needed, then add employee"""
        self.ensure_one()

        _logger.info(f"=" * 80)
        _logger.info(f"🔄 Starting _sync_dept_and_add_to_dl for {self.name}")

        if not self.department_id or not self.azure_user_id:
            _logger.warning(f"⚠️ Missing department or Azure User ID")
            return

        dept = self.department_id

        if not dept.azure_dl_id:
            _logger.info(f"🔍 Department '{dept.name}' has no DL, attempting auto-sync...")
            sync_result = dept.action_sync_dl_from_azure()
            dept.invalidate_recordset(['azure_dl_id', 'azure_dl_email'])
            dept = self.env['hr.department'].browse(dept.id)

            if not dept.azure_dl_id:
                _logger.warning(f"⚠️ Could not sync DL for department '{dept.name}'")
                return

        if dept.azure_dl_id:
            self._add_to_dept_dl()

        _logger.info(f"✅ Finished _sync_dept_and_add_to_dl")
        _logger.info(f"=" * 80)

    def _create_azure_email(self):
        """
        ✅ FINAL SOLUTION: TWO UNIQUE EMAILS USING SAME DOMAIN (techcarrot.ae)

        Creates:
        - work_email: firstname.lastname@techcarrot.ae (standard format)
        - azure_email: flastname@techcarrot.ae (short format - for Azure login)

        Both use @techcarrot.ae (the ONLY verified domain)
        But they are DIFFERENT and UNIQUE
        """
        self.ensure_one()

        _logger.info(f"{'=' * 80}")
        _logger.info(f"🔑 STARTING AZURE EMAIL CREATION - FINAL SOLUTION (Same Domain, Different Formats)")
        _logger.info(f"   Employee: {self.name} (ID: {self.id})")
        _logger.info(f"{'=' * 80}")

        IrConfig = self.env['ir.config_parameter'].sudo()

        tenant_id = IrConfig.get_param("azure_tenant_id")
        client_id = IrConfig.get_param("azure_client_id")
        client_secret = IrConfig.get_param("azure_client_secret")
        domain = IrConfig.get_param("azure_domain")  # techcarrot.ae (ONLY verified domain)

        _logger.info(f"📋 Configuration:")
        _logger.info(f"   Domain: {domain} (ONLY verified domain)")
        _logger.info(f"   Strategy: Different email formats on same domain")

        if not all([tenant_id, client_id, client_secret, domain]):
            _logger.error("❌ Azure credentials missing!")
            return

        try:
            # Generate base from name
            parts = self.name.strip().lower().replace('!', '').replace('.', '').split()
            first = parts[0]
            last = parts[-1] if len(parts) > 1 else first

            _logger.info(f"🔄 Processing: {self.name}")
            _logger.info(f"   First name: {first}")
            _logger.info(f"   Last name: {last}")

            # Get Azure AD token
            _logger.info(f"🔐 Requesting Azure AD token...")
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            token_data = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default"
            }

            token_response = requests.post(token_url, data=token_data, timeout=30)
            token_response.raise_for_status()
            token = token_response.json().get("access_token")

            if not token:
                _logger.error("❌ Failed to get access token")
                return

            _logger.info(f"✅ Azure AD token obtained")

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            # ✅ STRATEGY: Create TWO DIFFERENT email formats using SAME domain
            # Format 1: firstname.lastname@techcarrot.ae (for work_email)
            # Format 2: flastname@techcarrot.ae (for azure_email - Azure login)

            count = 1
            work_email_base = f"{first}.{last}"  # john.smith
            azure_email_base = f"{first[0]}{last}"  # jsmith

            work_email_unique = f"{work_email_base}@{domain}"  # john.smith@techcarrot.ae
            azure_email_unique = f"{azure_email_base}@{domain}"  # jsmith@techcarrot.ae

            _logger.info(f"🔍 Starting uniqueness check...")
            _logger.info(f"   work_email format: {work_email_base}@{domain}")
            _logger.info(f"   azure_email format: {azure_email_base}@{domain}")

            # Loop to find unique combination
            while count < 100:
                _logger.info(f"\n🔍 Attempt #{count}:")
                _logger.info(f"   Checking work_email: {work_email_unique}")
                _logger.info(f"   Checking azure_email: {azure_email_unique}")

                # Check 1: Odoo database - check BOTH emails don't exist
                existing_in_odoo = self.env['hr.employee'].search([
                    '&',
                    ('id', '!=', self.id),
                    '|',
                    ('work_email', '=', work_email_unique),
                    '|',
                    ('azure_email', '=', azure_email_unique),
                    '|',
                    ('work_email', '=', azure_email_unique),  # Cross-check
                    ('azure_email', '=', work_email_unique),  # Cross-check
                ], limit=1)

                if existing_in_odoo:
                    _logger.warning(f"⚠️ Email conflict in Odoo: {existing_in_odoo.name}")
                    count += 1
                    work_email_unique = f"{work_email_base}{count}@{domain}"
                    azure_email_unique = f"{azure_email_base}{count}@{domain}"
                    continue

                # Check 2: Azure AD - check azure_email (the login email)
                check_url = f"https://graph.microsoft.com/v1.0/users/{azure_email_unique}"
                check = requests.get(check_url, headers=headers, timeout=30)

                if check.status_code == 404:
                    # Azure email doesn't exist - now check work_email too
                    work_check_url = f"https://graph.microsoft.com/v1.0/users/{work_email_unique}"
                    work_check = requests.get(work_check_url, headers=headers, timeout=30)

                    if work_check.status_code == 404:
                        # Perfect! Both emails are available
                        _logger.info(f"✅ Both emails available!")
                        _logger.info(f"   work_email: {work_email_unique}")
                        _logger.info(f"   azure_email: {azure_email_unique}")
                        _logger.info(f"   ✅ They are DIFFERENT!")
                        break
                    else:
                        # work_email exists in Azure
                        _logger.warning(f"⚠️ work_email exists in Azure")
                        count += 1
                        work_email_unique = f"{work_email_base}{count}@{domain}"
                        azure_email_unique = f"{azure_email_base}{count}@{domain}"

                elif check.status_code == 200:
                    existing_user = check.json()
                    existing_display_name = existing_user.get('displayName', 'Unknown')
                    _logger.warning(f"⚠️ azure_email exists in Azure: {existing_display_name}")
                    count += 1
                    work_email_unique = f"{work_email_base}{count}@{domain}"
                    azure_email_unique = f"{azure_email_base}{count}@{domain}"
                else:
                    _logger.error(f"❌ Error checking Azure: {check.status_code}")
                    _logger.error(f"   Response: {check.text}")
                    return

            # ✅ Create user in Azure AD
            # userPrincipalName = azure_email (the short format - for LOGIN)
            # mail = work_email (the standard format - for BUSINESS EMAIL)

            _logger.info(f"\n📧 Creating Azure user:")
            _logger.info(f"   Display Name: {self.name}")
            _logger.info(f"   UserPrincipalName (LOGIN): {azure_email_unique}")
            _logger.info(f"   Mail (BUSINESS): {work_email_unique}")
            _logger.info(f"   Both use domain: {domain}")
            _logger.info(f"   But formats are DIFFERENT!")

            payload = {
                "accountEnabled": True,
                "displayName": self.name,
                "mailNickname": azure_email_unique.split('@')[0],
                "userPrincipalName": azure_email_unique,  # ← SHORT format (jsmith@techcarrot.ae) - for LOGIN
                "mail": work_email_unique,  # ← STANDARD format (john.smith@techcarrot.ae) - for BUSINESS
                "usageLocation": "AE",
                "passwordProfile": {
                    "forceChangePasswordNextSignIn": True,
                    "password": "Welcome@123"
                }
            }

            _logger.info(f"📤 Payload:")
            _logger.info(f"   {json.dumps(payload, indent=2)}")

            create_url = "https://graph.microsoft.com/v1.0/users"
            create_response = requests.post(
                create_url,
                headers=headers,
                data=json.dumps(payload),
                timeout=30
            )

            _logger.info(f"📥 Azure response status: {create_response.status_code}")

            if create_response.status_code == 201:
                user_data = create_response.json()
                azure_user_id = user_data.get("id")

                _logger.info(f"✅ Azure user created successfully!")
                _logger.info(f"   User ID: {azure_user_id}")

                # ✅ Update Odoo record with TWO DIFFERENT EMAILS
                self.write({
                    'work_email': work_email_unique,  # john.smith@techcarrot.ae (BUSINESS)
                    'azure_email': azure_email_unique,  # jsmith@techcarrot.ae (LOGIN)
                    'azure_user_id': azure_user_id
                })

                _logger.info(f"\n✅ Odoo record updated:")
                _logger.info(f"   work_email: {work_email_unique} (business - standard format)")
                _logger.info(f"   azure_email: {azure_email_unique} (login - short format)")
                _logger.info(f"   azure_user_id: {azure_user_id}")
                _logger.info(f"\n📝 User logs into Microsoft 365 with: {azure_email_unique}")
                _logger.info(f"📝 User receives business emails at: {work_email_unique}")
                _logger.info(f"✅ BOTH EMAILS ARE DIFFERENT!")

            else:
                error_response = create_response.json()
                error_msg = error_response.get('error', {}).get('message', 'Unknown error')
                _logger.error(f"❌ Failed to create Azure user")
                _logger.error(f"   Status: {create_response.status_code}")
                _logger.error(f"   Error: {error_msg}")
                _logger.error(f"   Full response: {json.dumps(error_response, indent=2)}")

        except UserError:
            raise
        except Exception as e:
            _logger.error(f"❌ Exception in _create_azure_email: {str(e)}")
            import traceback
            _logger.error(f"Full traceback:\n{traceback.format_exc()}")

        _logger.info(f"{'=' * 80}")
        _logger.info(f"✅ AZURE EMAIL CREATION COMPLETED")
        _logger.info(f"{'=' * 80}")

    def _check_and_assign_license(self):
        """Check if license already assigned, then assign if needed"""
        self.ensure_one()

        if not self.azure_user_id:
            _logger.error(f"❌ No Azure User ID for {self.name}")
            return False

        params = self.env['ir.config_parameter'].sudo()
        tenant = params.get_param("azure_tenant_id")
        client = params.get_param("azure_client_id")
        secret = params.get_param("azure_client_secret")
        license_sku = params.get_param("azure_license_sku")

        if not license_sku:
            _logger.warning("⚠️ No license SKU configured")
            return False

        try:
            token_resp = requests.post(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client,
                    "client_secret": secret,
                    "scope": "https://graph.microsoft.com/.default"
                },
                timeout=30
            ).json()

            token = token_resp.get("access_token")
            if not token:
                _logger.error("❌ No token for license check")
                return False

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            check_url = f"https://graph.microsoft.com/v1.0/users/{self.azure_user_id}/licenseDetails"
            check_response = requests.get(check_url, headers=headers, timeout=30)

            if check_response.status_code == 200:
                existing_licenses = check_response.json().get('value', [])
                for lic in existing_licenses:
                    if lic.get('skuId') == license_sku:
                        license_name = lic.get('skuPartNumber', 'Microsoft 365')
                        self.write({
                            'azure_license_assigned': True,
                            'azure_license_name': license_name
                        })
                        _logger.info(f"✅ {self.name} already has license: {license_name}")
                        return True

            _logger.info(f"🔄 Assigning license to {self.name}...")

            enable_payload = {"accountEnabled": True}
            requests.patch(
                f"https://graph.microsoft.com/v1.0/users/{self.azure_user_id}",
                headers=headers,
                json=enable_payload,
                timeout=30
            )

            license_payload = {
                "addLicenses": [{
                    "skuId": license_sku,
                    "disabledPlans": []
                }],
                "removeLicenses": []
            }

            license_response = requests.post(
                f"https://graph.microsoft.com/v1.0/users/{self.azure_user_id}/assignLicense",
                headers=headers,
                json=license_payload,
                timeout=30
            )

            if license_response.status_code == 200:
                sku_response = requests.get(
                    f"https://graph.microsoft.com/v1.0/subscribedSkus",
                    headers=headers,
                    timeout=30
                )

                license_name = "Microsoft 365"
                if sku_response.status_code == 200:
                    skus = sku_response.json().get('value', [])
                    for sku in skus:
                        if sku.get('skuId') == license_sku:
                            license_name = sku.get('skuPartNumber', 'Microsoft 365')
                            break

                self.write({
                    'azure_license_assigned': True,
                    'azure_license_name': license_name
                })
                _logger.info(f"✅ License assigned: {license_name}")
                return True
            else:
                error_data = license_response.json().get('error', {})
                error_msg = error_data.get('message', 'Unknown')

                if 'already' in error_msg.lower():
                    _logger.info(f"✅ License already assigned")
                    self.write({'azure_license_assigned': True})
                    return True

                _logger.error(f"❌ License assignment failed: {error_msg}")
                return False

        except Exception as e:
            _logger.error(f"❌ License check failed: {e}")
            return False

    def _add_to_dept_dl(self):
        """Add employee to department DL"""
        self.ensure_one()

        if not self.department_id or not self.azure_user_id:
            return

        dept = self.department_id
        if not dept.azure_dl_id:
            return

        try:
            params = self.env['ir.config_parameter'].sudo()
            tenant = params.get_param("azure_tenant_id")
            client = params.get_param("azure_client_id")
            secret = params.get_param("azure_client_secret")

            token_resp = requests.post(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client,
                    "client_secret": secret,
                    "scope": "https://graph.microsoft.com/.default"
                },
                timeout=30
            ).json()

            token = token_resp.get("access_token")
            if not token:
                return

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            check_url = f"https://graph.microsoft.com/v1.0/groups/{dept.azure_dl_id}/members/{self.azure_user_id}"
            check_response = requests.get(check_url, headers=headers, timeout=30)

            if check_response.status_code == 200:
                _logger.info(f"✅ {self.name} already in {dept.azure_dl_email}")
                return

            add_payload = {"@odata.id": f"https://graph.microsoft.com/v1.0/users/{self.azure_user_id}"}
            add_url = f"https://graph.microsoft.com/v1.0/groups/{dept.azure_dl_id}/members/$ref"

            add_response = requests.post(
                add_url,
                headers=headers,
                json=add_payload,
                timeout=30
            )

            if add_response.status_code == 204:
                _logger.info(f"✅ Successfully added {self.name} to {dept.azure_dl_email}")

        except Exception as e:
            _logger.error(f"❌ DL addition failed: {e}")

    def action_view_azure_user(self):
        """Open Azure AD user page"""
        self.ensure_one()
        if self.azure_user_id:
            return {
                'type': 'ir.actions.act_url',
                'url': f'https://portal.azure.com/#view/Microsoft_AAD_UsersAndTenants/UserProfileMenuBlade/~/overview/userId/{self.azure_user_id}',
                'target': 'new',
            }

    def action_unassign_license(self):
        """Button to unassign license"""
        # Keep your existing implementation
        pass

    def action_assign_license(self):
        """Button to assign license"""
        # Keep your existing implementation
        pass