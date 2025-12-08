import requests
import json
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HREmployee(models.Model):
    _inherit = 'hr.employee'

    # Field definitions - these will create database columns
    azure_email = fields.Char("Azure Email", readonly=True)
    azure_user_id = fields.Char("Azure User ID", readonly=True)
    azure_license_assigned = fields.Boolean("License Assigned", default=False, readonly=True)
    azure_license_name = fields.Char("License Name", readonly=True)

    @api.model
    def create(self, vals):
        """Automatically runs when Power Automate creates employee from SharePoint"""
        emp = super(HREmployee, self).create(vals)

        if emp.name:
            # Step 1: Create Azure email
            emp._create_azure_email()

            # Step 2: Assign license (only if email was created successfully)
            if emp.azure_user_id:
                emp.assign_azure_license()

            # Step 3: Add to department DL (only if user exists)
            if emp.department_id and emp.azure_user_id:
                emp._add_to_dept_dl()

        return emp

    def _create_azure_email(self):
        """Create unique email in Azure AD"""
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
                    count += 1
                    unique_email = f"{base}{count}@{domain}"
                    _logger.info(f"🔄 Email exists, trying: {unique_email}")
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
                _logger.info(f"✅ SUCCESS! Created: {unique_email} with ID: {self.azure_user_id}")
            else:
                error = create_response.json().get('error', {}).get('message', 'Unknown error')
                _logger.error(f"❌ Failed to create user: {error}")

        except Exception as e:
            _logger.error(f"❌ Exception in _create_azure_email: {str(e)}")

    def assign_azure_license(self):
        """Assign Microsoft 365 license to user"""
        if not self.azure_user_id:
            _logger.error(f"❌ Cannot assign license: No Azure User ID for {self.name}")
            return False

        params = self.env['ir.config_parameter'].sudo()
        tenant = params.get_param("azure_tenant_id")
        client = params.get_param("azure_client_id")
        secret = params.get_param("azure_client_secret")
        license_sku = params.get_param("azure_license_sku")

        if not license_sku:
            _logger.warning("⚠️ No license SKU configured. Skipping license assignment.")
            return False

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
                _logger.error("❌ Failed to get access token for license assignment")
                return False

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            # Assign license
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
                _logger.info(f"✅ License '{license_name}' assigned to {self.name}")
                return True
            else:
                error = license_response.json().get('error', {}).get('message', 'Unknown')
                _logger.error(f"❌ Failed to assign license: {error}")
                return False

        except Exception as e:
            _logger.error(f"❌ License assignment failed: {e}")
            return False

    def _add_to_dept_dl(self):
        """Add employee to department DL"""
        if not self.department_id or not self.azure_user_id:
            _logger.warning(f"⚠️ Skipping DL: dept={self.department_id}, user_id={self.azure_user_id}")
            return

        dept = self.department_id

        # Create DL if doesn't exist
        if not dept.azure_dl_id:
            _logger.info(f"🔄 Department {dept.name} has no DL, creating...")
            dept.create_dl()

        if dept.azure_dl_id:
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

                add_response = requests.post(
                    f"https://graph.microsoft.com/v1.0/groups/{dept.azure_dl_id}/members/$ref",
                    headers=headers,
                    json={"@odata.id": f"https://graph.microsoft.com/v1.0/users/{self.azure_user_id}"},
                    timeout=30
                )

                if add_response.status_code == 204:
                    _logger.info(f"✅ Added {self.name} to {dept.azure_dl_email}")
                elif add_response.status_code == 400:
                    _logger.info(f"ℹ️ {self.name} already in {dept.azure_dl_email}")
                else:
                    _logger.error(f"❌ Failed to add to DL: {add_response.status_code}")

            except Exception as e:
                _logger.error(f"❌ Failed to add to DL: {e}")

    def action_view_azure_user(self):
        """Open Azure AD user page in browser"""
        if self.azure_user_id:
            return {
                'type': 'ir.actions.act_url',
                'url': f'https://portal.azure.com/#view/Microsoft_AAD_UsersAndTenants/UserProfileMenuBlade/~/overview/userId/{self.azure_user_id}',
                'target': 'new',
            }