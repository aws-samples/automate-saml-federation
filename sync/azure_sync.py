import logging
import os
import boto3
import json
import requests
import uuid
from botocore.exceptions import ClientError
import re
from base64 import b64decode

log_level = int(os.environ.get('LOG_LEVEL', logging.INFO))
logger = logging.getLogger()
logger.setLevel(log_level)

session = boto3.session.Session()
ssmc = session.client('ssm')
# kms = session.client('kms')

# GRAPH_URL = "https://graph.windows.net/"
GRAPH_URL = "https://graph.microsoft.com"
CLIENT_ID = "1950a258-227b-4e31-a9cf-717495945fc2"
PREFIX = 'iam-saml'
azure_user = None
azure_pass = None
azure_tenant = None
ad_auth_url = None
ad_app_url = None
req_header = None
msiam_access_id = None
sso_app_obj_id = None
access_token = None


def init_function():
    try:
        global azure_user, azure_pass, azure_tenant, ad_auth_url, msiam_access_id, sso_app_obj_id, ad_app_url, access_token, req_header
        # cyphered_secret = ssmc.get_parameter(Name=f'{PREFIX}.secret', WithDecryption=False)['Parameter']['Value']
        # secret = json.loads(kms.decrypt(CiphertextBlob=b64decode(cyphered_secret))['Plaintext'].decode("utf-8"))
        secret_json = ssmc.get_parameter(Name=f'{PREFIX}.secret', WithDecryption=True)['Parameter']['Value']
        secret = json.loads(secret_json)
        azure_user = secret.get('AzureUser')
        azure_pass = secret.get('AzurePassword')
        azure_tenant = ssmc.get_parameter(Name=f'{PREFIX}.tenant_name')['Parameter']['Value']
        sso_app_obj_id = ssmc.get_parameter(Name=f'{PREFIX}.app_object_id')['Parameter']['Value']
        msiam_access_id = ssmc.get_parameter(Name=f'{PREFIX}.msiam_access_id')
        ad_auth_url = f"https://login.microsoftonline.com/{azure_tenant}/oauth2/token"
        #ad_principals_url = f'https://graph.microsoft.com/beta/{azure_tenant}/servicePrincipals/{sso_app_id}'
        ad_app_url = f'https://graph.microsoft.com/beta/{azure_tenant}/applications/{sso_app_obj_id}'
        access_token = authenticate()
        req_header = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        logger.debug(f'azure token -> {req_header}')
    except ClientError as e:
        logger.error(f'Some parameters could not be retrieved: {str(e)}')
        exit(-1)


def authenticate():
    payload = {
        "resource": GRAPH_URL,
        "client_id": CLIENT_ID,
        "grant_type": "password",
        "username": azure_user,
        "password": azure_pass,
        "scope": "openid",
        "scp": "User.ReadBasic.All; User.Read.All; User.ReadWrite.All; Directory.Read.All; Directory.ReadWrite.All; Directory.AccessAsUser.All"
    }
    logger.debug(payload)
    rsp = requests.post(ad_auth_url, data=payload)
    msg = rsp.json()
    if rsp.status_code > 399:
        logger.error(f'{msg.get("error")}:{msg.get("error_description")}')
        rsp.raise_for_status()
    # logger.debug(f'Response -> {rsp.text}')
    return msg.get('access_token')


def filter_app_role_by_display_name(app_roles, display_name):
    for r in app_roles:
        if r.get('displayName') == display_name:
            return r
    return None


def get_existing_app_roles():
    rsp = requests.get(url=ad_app_url, headers=req_header)
    msg = rsp.json()
    if rsp.status_code > 399:
        logger.error(f'Failed to request existing roles with URL {ad_app_url}: {msg.get("error")} > {msg.get("error_description")}')
        rsp.raise_for_status()
    return msg.get('appRoles')


def get_deleted_roles(new_roles, existing_roles):
    deleted_roles = list()
    new_roles_set = {r.get('displayName') for r in new_roles}
    existing_roles_set = {r.get('displayName') for r in existing_roles if r.get('displayName') != 'msiam_access'}
    deleted_roles_set = existing_roles_set.difference(new_roles_set)
    for deleted_role_name in deleted_roles_set:
        deleted_role = list(filter(lambda r: r.get('displayName') == deleted_role_name, existing_roles)).pop()
        if deleted_role:
            deleted_role.update(isEnabled=False)
            deleted_roles.append(deleted_role)
    # print(f'NEW -> {new_roles}')
    # print(f'EXISTING -> {existing_roles}')
    return deleted_roles


def create_app_role(provider_arn, role_arn, existing_app_roles):
    account_number = re.search('arn:aws:iam::(.+?):', role_arn).group(1)
    role_name = re.search('/(.+?)$', role_arn).group(1)
    role_name = f'AWS {account_number} - {role_name}'
    existing_app_role = filter_app_role_by_display_name(existing_app_roles, role_name)
    return {
        "allowedMemberTypes": [
            "User"
        ],
        "description": role_name,
        "displayName": role_name,
        "id": existing_app_role.get('id') if existing_app_role else str(uuid.uuid4()),
        "isEnabled": existing_app_role.get('isEnabled') if existing_app_role else True,
        "origin": "Application",
        "value": f'{role_arn},{provider_arn}'
    }


def update_roles(app_roles):
    data = {
        "appRoles": app_roles
    }
    logger.info(f'PATCHING ROLES -> {json.dumps(data, indent=4)}')

    prsp = requests.patch(url=ad_app_url, headers=req_header, data=json.dumps(data))
    msg = prsp.json() if prsp.text and "application/json" in prsp.headers.get('content-type') else {}
    if prsp.status_code > 399:
        logger.error(f"Couldn't patch the roles due to {msg.get('error')}:{msg.get('error_description')}")
        prsp.raise_for_status()
    logger.info(f'PATCH result {prsp.status_code}')


def delete_roles(new_roles, deleted_roles):
    if len(deleted_roles) > 0:
        logger.warning('Skipping role deletion since strange Azure error')
        logger.info(f'DELETING ROLES -> {json.dumps(deleted_roles, indent=4)}')
        deleted_role_names = {r.get('displayName') for r in deleted_roles if r.get('displayName') != 'msiam_access'}
        remaining_roles = [r for r in new_roles if r.get('displayName') not in deleted_role_names]
        update_roles(remaining_roles)
    else:
        logger.info("There are no roles to delete.")


def handle(roles_for_providers: dict):
    if not azure_user or not azure_pass or not azure_tenant:
        init_function()
    existing_app_roles = get_existing_app_roles()

    new_app_roles = list()
    msiam_access_role = list(filter(lambda r: r.get('description') == 'msiam_access', existing_app_roles)).pop()
    new_app_roles.append(msiam_access_role)

    for provider, roles in roles_for_providers.items():
        for role in roles:
            new_app_roles.append(create_app_role(provider, role, existing_app_roles))

    deleted_roles = get_deleted_roles(new_app_roles, existing_app_roles)
    new_app_roles.extend(deleted_roles)
    update_roles(new_app_roles)
    delete_roles(new_app_roles, deleted_roles)
