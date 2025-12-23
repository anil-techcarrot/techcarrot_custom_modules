import requests
import json
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HREmployee(models.Model):
    _inherit = 'hr.employee'

    azure_email = fields.Char("Azure Email", readonly=True)
    azure_user_id = fields.Char("Azure User ID", readonly=True)
    azure_license_assigned = fields.Boolean("License Assigned", default=False, readonly=True)
    azure_license_name = fields.Char("License Name", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        """Automatically runs when employee is created - ODOO 19"""
        employees = super().create(vals_list)

        for emp in employees:
            if emp.name:
                # Step 1: Create Azure user
                emp._create_azure_email()

                # Step 2: Assign license (check if not already assigned)
                if emp.azure_user_id:
                    emp._check_and_assign_license()

                # Step 3: Add to department DL (check if not already member)
                if emp.department_id and emp.azure_user_id:
                    # Auto-sync department DL if not configured
                    if not emp.department_id.azure_dl_id:
                        emp.department_id.action_sync_dl_from_azure()

                    # Add to DL if it exists
                    if emp.department_id.azure_dl_id:
                        emp._add_to_dept_dl()

        return employees

    def _create_azure_email(self):
        """Create unique email in Azure AD"""
        self.ensure_one()

        IrConfig = self.env['ir.config_parameter'].sudo()

        tenant_id = IrConfig.get_param("azure_tenant_id")
        client_id = IrConfig.get_param("azure_client_id")
        client_secret = IrConfig.get_param("azure_client_secret")
        domain = IrConfig.get_param("azure_domain")

        if not all([tenant_id, client_id, client_secret, domain]):
            _logger.error("❌ Azure credentials missing in System Parameters!")
            return

        try:
            # Generate email from name
            parts = self.name.strip().lower().split()
            first = parts[0]
            last = parts[-1] if len(parts) > 1 else first
            base = f"{first}.{last}"
            email = f"{base}@{domain}"

            _logger.info(f"🔄 Processing: {self.name} → {email}")

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

            # Check for unique email
            count = 1
            unique_email = email

            while count < 100:
                check_url = f"https://graph.microsoft.com/v1.0/users/{unique_email}"
                check = requests.get(check_url, headers=headers, timeout=30)

                if check.status_code == 404:
                    _logger.info(f"✅ Email available: {unique_email}")
                    break
                elif check.status_code == 200:
                    # Email exists, check if it's the same user
                    existing_user = check.json()
                    existing_id = existing_user.get('id')

                    # If this employee already has this Azure user, link it
                    if not self.azure_user_id:
                        self.write({
                            'azure_email': unique_email,
                            'work_email': unique_email,
                            'azure_user_id': existing_id
                        })
                        _logger.info(f"ℹ️ Linked existing Azure user: {unique_email}")
                        return

                    count += 1
                    unique_email = f"{base}{count}@{domain}"
                    _logger.info(f"🔄 Trying: {unique_email}")
                else:
                    _logger.error(f"❌ Error checking email: {check.status_code}")
                    return

            # Create user in Azure AD
            payload = {
                "accountEnabled": True,
                "displayName": self.name,
                "mailNickname": unique_email.split('@')[0],
                "userPrincipalName": unique_email,
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
                    'azure_email': unique_email,
                    'work_email': unique_email,
                    'azure_user_id': user_data.get("id")
                })
                _logger.info(f"✅ Created: {unique_email} | ID: {self.azure_user_id}")
            else:
                error = create_response.json().get('error', {}).get('message', 'Unknown')
                _logger.error(f"❌ Failed to create user: {error}")

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

            # STEP 1: Check if user already has license in Azure
            check_url = f"https://graph.microsoft.com/v1.0/users/{self.azure_user_id}/licenseDetails"
            check_response = requests.get(check_url, headers=headers, timeout=30)

            if check_response.status_code == 200:
                existing_licenses = check_response.json().get('value', [])
                for lic in existing_licenses:
                    if lic.get('skuId') == license_sku:
                        # License already exists in Azure
                        license_name = lic.get('skuPartNumber', 'Microsoft 365')
                        self.write({
                            'azure_license_assigned': True,
                            'azure_license_name': license_name
                        })
                        _logger.info(f"ℹ️ {self.name} already has license: {license_name}")
                        return True

            # STEP 2: License not found, assign it
            _logger.info(f"🔄 Assigning license to {self.name}...")

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

                # Handle "already assigned" error
                if 'already' in error_msg.lower():
                    _logger.info(f"ℹ️ License already assigned (Azure reported)")
                    self.write({'azure_license_assigned': True})
                    return True

                _logger.error(f"❌ License assignment failed: {error_msg}")
                return False

        except Exception as e:
            _logger.error(f"❌ License check failed: {e}")
            return False

    def _add_to_dept_dl(self):
        """Add employee to department DL - CHECK IF ALREADY MEMBER"""
        self.ensure_one()

        if not self.department_id or not self.azure_user_id:
            _logger.warning(f"⚠️ Missing dept or user_id for {self.name}")
            return

        dept = self.department_id

        # Check if department has DL configured
        if not dept.azure_dl_id:
            _logger.error(f"❌ Department '{dept.name}' has no DL configured")
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
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            # STEP 1: Check if user is already a member
            check_url = f"https://graph.microsoft.com/v1.0/groups/{dept.azure_dl_id}/members/{self.azure_user_id}"
            check_response = requests.get(check_url, headers=headers, timeout=30)

            if check_response.status_code == 200:
                _logger.info(f"ℹ️ {self.name} already in {dept.azure_dl_email}")
                return

            # STEP 2: Not a member, add them
            add_response = requests.post(
                f"https://graph.microsoft.com/v1.0/groups/{dept.azure_dl_id}/members/$ref",
                headers=headers,
                json={"@odata.id": f"https://graph.microsoft.com/v1.0/users/{self.azure_user_id}"},
                timeout=30
            )

            if add_response.status_code == 204:
                _logger.info(f"✅ Added {self.name} to {dept.azure_dl_email}")
            elif add_response.status_code == 400:
                error = add_response.json().get('error', {})
                if 'already exist' in error.get('message', '').lower():
                    _logger.info(f"ℹ️ {self.name} already in {dept.azure_dl_email} (Azure confirmed)")
                else:
                    _logger.error(f"❌ Failed to add: {error.get('message', 'Unknown')}")
            else:
                _logger.error(f"❌ Failed to add to DL: HTTP {add_response.status_code}")

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

    def action_assign_license_manual(self):
        """Manual button to assign license"""
        self.ensure_one()
        self._check_and_assign_license()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': 'License assignment completed. Check logs for details.',
                'type': 'success',
            }
        }

    def action_show_available_licenses(self):
        """Display all available licenses with SKU IDs"""
        params = self.env['ir.config_parameter'].sudo()
        tenant = params.get_param("azure_tenant_id")
        client = params.get_param("azure_client_id")
        secret = params.get_param("azure_client_secret")

        if not all([tenant, client, secret]):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': 'Azure credentials missing in System Parameters',
                    'type': 'danger',
                }
            }

        try:
            # Get access token
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
                raise Exception("Failed to get access token")

            # Get all subscribed SKUs
            response = requests.get(
                "https://graph.microsoft.com/v1.0/subscribedSkus",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30
            )

            if response.status_code == 200:
                skus = response.json().get('value', [])

                # Log detailed information
                log_message = "\n" + "=" * 80 + "\n"
                log_message += "AVAILABLE LICENSES IN YOUR TENANT\n"
                log_message += "=" * 80 + "\n\n"

                for sku in skus:
                    sku_id = sku.get('skuId')
                    sku_name = sku.get('skuPartNumber')
                    total = sku.get('prepaidUnits', {}).get('enabled', 0)
                    consumed = sku.get('consumedUnits', 0)
                    available = total - consumed
                    status = sku.get('capabilityStatus')

                    log_message += f"License: {sku_name}\n"
                    log_message += f"SKU ID: {sku_id}\n"
                    log_message += f"Status: {status}\n"
                    log_message += f"Total: {total} | Used: {consumed} | Available: {available}\n"
                    log_message += "-" * 80 + "\n"

                _logger.info(log_message)

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': '✅ License Information Retrieved',
                        'message': f'Found {len(skus)} license types. Check Odoo server logs for complete details with SKU IDs.',
                        'type': 'success',
                        'sticky': True,
                    }
                }
            else:
                raise Exception(f"API returned status {response.status_code}")

        except Exception as e:
            _logger.error(f"❌ Error fetching licenses: {e}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'message': f'Error: {str(e)}',
                    'type': 'danger',
                }
            }