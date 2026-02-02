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

        # VALIDATE work_email for duplicates BEFORE creating
        for vals in vals_list:
            if vals.get('work_email'):
                self._validate_work_email(vals.get('work_email'))

        employees = super().create(vals_list)

        for emp in employees:
            if emp.name:
                # Step 1: Create Azure user
                emp._create_azure_email()

                # Step 2: Add to department DL automatically
                if emp.department_id and emp.azure_user_id:
                    emp._sync_dept_and_add_to_dl()

        return employees

    def write(self, vals):
        """Monitor department changes and validate email changes"""

        # VALIDATE work_email if it's being changed
        if 'work_email' in vals and vals['work_email']:
            for emp in self:
                emp._validate_work_email(vals['work_email'], exclude_id=emp.id)

        result = super().write(vals)

        # If department changed, update DL membership automatically
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
        """Sync department DL if needed, then add employee - FULLY AUTOMATIC"""
        self.ensure_one()

        _logger.info(f"=" * 80)
        _logger.info(f"🔄 Starting _sync_dept_and_add_to_dl for {self.name}")
        _logger.info(f"   Employee ID: {self.id}")
        _logger.info(f"   Azure User ID: {self.azure_user_id}")
        _logger.info(f"   Department: {self.department_id.name if self.department_id else 'None'}")
        _logger.info(f"   Department ID: {self.department_id.id if self.department_id else 'None'}")

        if not self.department_id:
            _logger.warning(f"⚠️ No department for {self.name}")
            return

        if not self.azure_user_id:
            _logger.warning(f"⚠️ No Azure User ID for {self.name}")
            return

        dept = self.department_id

        _logger.info(f"📋 Current Department State:")
        _logger.info(f"   Name: {dept.name}")
        _logger.info(f"   DL ID: {dept.azure_dl_id}")
        _logger.info(f"   DL Email: {dept.azure_dl_email}")

        # If department has no DL configured, try to sync it automatically
        if not dept.azure_dl_id:
            _logger.info(f"🔍 Department '{dept.name}' has no DL, attempting auto-sync...")

            # Call sync
            sync_result = dept.action_sync_dl_from_azure()
            _logger.info(f"   Sync result: {sync_result}")

            # CRITICAL FIX: Invalidate cache AND re-browse to get fresh data
            dept.invalidate_recordset(['azure_dl_id', 'azure_dl_email'])

            # Re-browse the department record from database
            dept = self.env['hr.department'].browse(dept.id)

            # Log the values after refresh
            _logger.info(f"📊 After sync - DL ID: {dept.azure_dl_id}")
            _logger.info(f"📊 After sync - DL Email: {dept.azure_dl_email}")

            if not dept.azure_dl_id:
                _logger.warning(f"⚠️ Could not sync DL for department '{dept.name}'")
                _logger.warning(f"   Please create DL_{dept.name}@techcarrot.ae in Azure")
                return
        else:
            _logger.info(f"✅ Department already has DL configured")

        # If DL is now configured, add employee
        if dept.azure_dl_id:
            _logger.info(f"📌 Department '{dept.name}' linked to {dept.azure_dl_email}")
            _logger.info(f"   DL ID: {dept.azure_dl_id}")
            _logger.info(f"   Employee: {self.name}")
            _logger.info(f"   User ID: {self.azure_user_id}")

            # Add employee to DL
            _logger.info(f"🔄 Calling _add_to_dept_dl()...")
            try:
                self._add_to_dept_dl()
                _logger.info(f"✅ _add_to_dept_dl() completed")
            except Exception as e:
                _logger.error(f"❌ Exception in _add_to_dept_dl(): {e}")
                import traceback
                _logger.error(traceback.format_exc())
        else:
            _logger.error(f"❌ Department '{dept.name}' has no DL configured after sync")
            _logger.error(f"   DL ID is still: {dept.azure_dl_id}")
            _logger.error(f"   DL Email is still: {dept.azure_dl_email}")

        _logger.info(f"✅ Finished _sync_dept_and_add_to_dl for {self.name}")
        _logger.info(f"=" * 80)

    def _create_azure_email(self):
        """Create unique email in Azure AD with @email.com domain"""
        self.ensure_one()

        IrConfig = self.env['ir.config_parameter'].sudo()

        tenant_id = IrConfig.get_param("azure_tenant_id")
        client_id = IrConfig.get_param("azure_client_id")
        client_secret = IrConfig.get_param("azure_client_secret")
        domain = IrConfig.get_param("azure_domain")  # This is techcarrot.ae

        if not all([tenant_id, client_id, client_secret, domain]):
            _logger.error("❌ Azure credentials missing in System Parameters!")
            return

        try:
            # Generate base email from name
            parts = self.name.strip().lower().replace('!', '').split()
            first = parts[0]
            last = parts[-1] if len(parts) > 1 else first
            base = f"{first}.{last}"

            _logger.info(f"🔄 Processing: {self.name} → base: {base}")

            # Get Azure AD token
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

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            # Check for unique email in BOTH Odoo AND Azure
            count = 1
            unique_email = f"{base}@{domain}"  # For work_email (techcarrot.ae)
            azure_unique_email = f"{base}@techcarrot.onmicrosoft.com"  # For Azure AD (VERIFIED DOMAIN)

            while count < 100:
                _logger.info(f"🔍 Trying Work Email: {unique_email}")
                _logger.info(f"🔍 Trying Azure Email: {azure_unique_email}")

                # Check 1: Odoo database (check both emails)
                existing_in_odoo = self.env['hr.employee'].search([
                    '&',
                    ('id', '!=', self.id),
                    '|',
                    ('azure_email', '=', azure_unique_email),
                    ('work_email', '=', unique_email),
                ], limit=1)

                if existing_in_odoo:
                    _logger.warning(f"⚠️ Email exists in Odoo ({existing_in_odoo.name})")
                    count += 1
                    unique_email = f"{base}{count}@{domain}"
                    azure_unique_email = f"{base}{count}@techcarrot.onmicrosoft.com"
                    continue

                # Check 2: Azure AD (check azure_unique_email)
                check_url = f"https://graph.microsoft.com/v1.0/users/{azure_unique_email}"
                check = requests.get(check_url, headers=headers, timeout=30)

                if check.status_code == 404:
                    _logger.info(f"✅ Azure Email available: {azure_unique_email}")
                    _logger.info(f"✅ Work Email available: {unique_email}")
                    break

                elif check.status_code == 200:
                    existing_user = check.json()
                    existing_display_name = existing_user.get('displayName')
                    _logger.warning(f"⚠️ {azure_unique_email} exists in Azure ({existing_display_name})")

                    count += 1
                    unique_email = f"{base}{count}@{domain}"
                    azure_unique_email = f"{base}{count}@techcarrot.onmicrosoft.com"

                else:
                    _logger.error(f"❌ Error checking email: {check.status_code}")
                    return

            # Create user in Azure AD with @techcarrot.onmicrosoft.com domain
            payload = {
                "accountEnabled": True,
                "displayName": self.name,
                "mailNickname": azure_unique_email.split('@')[0],
                "userPrincipalName": azure_unique_email,  # ← Uses @techcarrot.onmicrosoft.com
                "usageLocation": "AE",
                "passwordProfile": {
                    "forceChangePasswordNextSignIn": True,
                    "password": "Welcome@123"
                }
            }

            create_url = "https://graph.microsoft.com/v1.0/users"
            create_response = requests.post(
                create_url,
                headers=headers,
                data=json.dumps(payload),
                timeout=30
            )

            if create_response.status_code == 201:
                user_data = create_response.json()
                self.write({
                    'azure_email': azure_unique_email,  # ← Saves name@techcarrot.onmicrosoft.com
                    'work_email': unique_email,          # ← Saves name@techcarrot.ae
                    'azure_user_id': user_data.get("id")
                })
                _logger.info(f"✅ Azure Email: {azure_unique_email}")
                _logger.info(f"✅ Work Email: {unique_email}")
                _logger.info(f"✅ Azure User ID: {self.azure_user_id}")
            else:
                error = create_response.json().get('error', {}).get('message', 'Unknown')
                _logger.error(f"❌ Failed to create user: {error}")

        except UserError:
            raise
        except Exception as e:
            _logger.error(f"❌ Exception: {str(e)}")

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
            # Get token
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

            # Check if user already has license in Azure
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

            # License not found, assign it
            _logger.info(f"🔄 Assigning license to {self.name}...")

            # Re-enable account if it was disabled
            enable_payload = {"accountEnabled": True}
            enable_response = requests.patch(
                f"https://graph.microsoft.com/v1.0/users/{self.azure_user_id}",
                headers=headers,
                json=enable_payload,
                timeout=30
            )

            if enable_response.status_code == 200:
                _logger.info(f"✅ Account enabled for {self.name}")
            else:
                _logger.warning(f"⚠️ Could not enable account (may already be enabled)")

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
                # Get license name
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
        """Add employee to department DL - WITH DUPLICATE PREVENTION"""
        self.ensure_one()

        if not self.department_id or not self.azure_user_id:
            _logger.warning(f"⚠️ Missing dept or user_id for {self.name}")
            return

        dept = self.department_id

        if not dept.azure_dl_id:
            _logger.error(f"❌ Department '{dept.name}' has no DL configured")
            return

        _logger.info(f"🔄 Starting DL addition for {self.name}")
        _logger.info(f"   Department: {dept.name}")
        _logger.info(f"   DL Email: {dept.azure_dl_email}")
        _logger.info(f"   DL ID: {dept.azure_dl_id}")
        _logger.info(f"   User ID: {self.azure_user_id}")

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
                _logger.error("❌ Failed to get token for DL addition")
                return

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            # Check if already a member
            check_url = f"https://graph.microsoft.com/v1.0/groups/{dept.azure_dl_id}/members/{self.azure_user_id}"
            _logger.info(f"🔍 Checking membership: {check_url}")
            check_response = requests.get(check_url, headers=headers, timeout=30)

            if check_response.status_code == 200:
                _logger.info(f"✅ {self.name} already in {dept.azure_dl_email}")
                return
            elif check_response.status_code == 404:
                _logger.info(f"📝 User not in DL, will add now")
            else:
                _logger.warning(f"⚠️ Unexpected status checking membership: {check_response.status_code}")

            # Not a member, add them
            _logger.info(f"➕ Adding {self.name} to {dept.azure_dl_email}...")

            add_payload = {"@odata.id": f"https://graph.microsoft.com/v1.0/users/{self.azure_user_id}"}
            add_url = f"https://graph.microsoft.com/v1.0/groups/{dept.azure_dl_id}/members/$ref"

            _logger.info(f"📤 POST {add_url}")
            _logger.info(f"📦 Payload: {json.dumps(add_payload)}")

            add_response = requests.post(
                add_url,
                headers=headers,
                json=add_payload,
                timeout=30
            )

            _logger.info(f"📥 Response Status: {add_response.status_code}")

            if add_response.status_code == 204:
                _logger.info(f"✅ Successfully added {self.name} to {dept.azure_dl_email}")
            elif add_response.status_code == 400:
                error = add_response.json().get('error', {})
                error_msg = error.get('message', 'Unknown')
                if 'already exist' in error_msg.lower():
                    _logger.info(f"✅ {self.name} already in {dept.azure_dl_email}")
                else:
                    _logger.error(f"❌ Failed to add: {error_msg}")
                    _logger.error(f"   Full error: {json.dumps(error)}")
            else:
                _logger.error(f"❌ Failed: HTTP {add_response.status_code}")
                try:
                    error_detail = add_response.json()
                    _logger.error(f"   Error details: {json.dumps(error_detail)}")
                except:
                    _logger.error(f"   Response text: {add_response.text}")

        except Exception as e:
            _logger.error(f"❌ DL addition failed: {e}")
            import traceback
            _logger.error(traceback.format_exc())

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
        """Button to unassign license from employee"""
        self.ensure_one()

        if not self.azure_user_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': 'No Azure user found',
                    'type': 'warning',
                }
            }

        if not self.azure_license_assigned:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': 'No license to unassign',
                    'type': 'info',
                }
            }

        result = self._unassign_azure_license()

        if result:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f'License unassigned and account disabled for {self.name}',
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': 'Failed to unassign license',
                    'type': 'danger',
                }
            }

    def _unassign_azure_license(self):
        """Unassign license, disable account, and verify the changes"""
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
            # Get token
            token_resp = requests.post(
                f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client,
                    "client_secret": secret,
                    "scope": "https://graph.microsoft.com/.default"
                },
                timeout=30
            )

            if token_resp.status_code != 200:
                _logger.error(f"❌ Failed to get token: {token_resp.text}")
                return False

            token = token_resp.json().get("access_token")
            if not token:
                _logger.error("❌ No access token in response")
                return False

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            _logger.info(f"{'=' * 80}")
            _logger.info(f"🔄 Starting license removal and account disable for {self.name}")
            _logger.info(f"   User ID: {self.azure_user_id}")
            _logger.info(f"{'=' * 80}")

            # STEP 1: Remove the license
            _logger.info(f"📝 Step 1/3: Removing license...")

            license_payload = {
                "addLicenses": [],
                "removeLicenses": [license_sku]
            }

            license_response = requests.post(
                f"https://graph.microsoft.com/v1.0/users/{self.azure_user_id}/assignLicense",
                headers=headers,
                json=license_payload,
                timeout=30
            )

            if license_response.status_code == 200:
                _logger.info(f"✅ License removed successfully")
            else:
                error_data = license_response.json().get('error', {})
                error_msg = error_data.get('message', 'Unknown')
                if 'does not have a corresponding license' in error_msg:
                    _logger.info(f"✅ User doesn't have a license")
                else:
                    _logger.error(f"❌ Failed to remove license: {error_msg}")

            # STEP 2: Revoke all sessions
            _logger.info(f"📝 Step 2/3: Revoking all active sessions...")

            revoke_response = requests.post(
                f"https://graph.microsoft.com/v1.0/users/{self.azure_user_id}/revokeSignInSessions",
                headers=headers,
                timeout=30
            )

            if revoke_response.status_code in [200, 204]:
                _logger.info(f"✅ Sessions revoked successfully")
            else:
                _logger.warning(f"⚠️ Could not revoke sessions: {revoke_response.status_code}")

            # STEP 3: Disable the account
            _logger.info(f"📝 Step 3/3: Disabling account...")

            disable_payload = {"accountEnabled": False}
            disable_response = requests.patch(
                f"https://graph.microsoft.com/v1.0/users/{self.azure_user_id}",
                headers=headers,
                json=disable_payload,
                timeout=30
            )

            if disable_response.status_code in [200, 204]:
                _logger.info(f"✅ Account disabled successfully")
            else:
                _logger.error(f"❌ Failed to disable account: {disable_response.status_code}")
                return False

            # Update Odoo record
            self.write({
                'azure_license_assigned': False,
                'azure_license_name': False
            })

            _logger.info(f"{'=' * 80}")
            _logger.info(f"✅ PROCESS COMPLETED for {self.name}")
            _logger.info(f"{'=' * 80}")

            return True

        except Exception as e:
            _logger.error(f"❌ EXCEPTION OCCURRED: {e}")
            import traceback
            _logger.error(f"Full traceback:\n{traceback.format_exc()}")
            return False

    def action_assign_license(self):
        """Button to manually assign license to employee"""
        self.ensure_one()

        if not self.azure_user_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': 'No Azure user found',
                    'type': 'warning',
                }
            }

        if self.azure_license_assigned:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': 'License already assigned',
                    'type': 'info',
                }
            }

        # Check if licenses are available
        license_config = self.env['azure.license.config'].search([
            ('available_licenses', '>', 0)
        ], limit=1)

        if not license_config:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': '⚠️ No licenses available! Please purchase more licenses or unassign from other users.',
                    'type': 'warning',
                    'sticky': True
                }
            }

        result = self._check_and_assign_license()

        if result:
            # Refresh license count
            self.env['azure.license.config'].search([]).action_sync_licenses_from_azure()

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f'✅ License assigned to {self.name}',
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': 'Failed to assign license',
                    'type': 'danger',
                }
            }