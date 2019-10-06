import json
import logging
import os
from sync.util import make_response
import boto3
from boto3.session import Session
import xml.etree.ElementTree as et
import importlib

session = boto3.session.Session()
stsc = session.client("sts")
orgs = session.client('organizations')
ssmc = session.client('ssm')
log_level = int(os.environ.get('LOG_LEVEL', logging.INFO))
saml_connector = os.environ.get('SAML_CONNECTOR', 'sync.azure_sync')
iam_reader_role_name = os.environ.get('IAM_READER_ROLE', 'AWS_IAM_AAD_UpdateTask_CrossAccountRole')
logger = logging.getLogger()
logger.setLevel(log_level)
PREFIX = 'iam-saml'
saml_id = None
saml_entity_id = None
sub_accounts: list = None
root_account_id = None

def init_params():
    global saml_id, saml_entity_id, sso_app_id
    try:
        saml_id = ssmc.get_parameter(Name=f'{PREFIX}.saml_id', WithDecryption=True)['Parameter']['Value'] #SAMLMetaDataEntityDescriptorID
        saml_entity_id = ssmc.get_parameter(Name=f'{PREFIX}.saml_entity_id', WithDecryption=True)['Parameter']['Value'] #SAMLMetaDataEntityDescriptorEntityID
    except Exception as e:
        logger.error(f'Parameters could not be initialised {str(e)}')
        exit(-1)

def cache_accounts():
    global sub_accounts, root_account_id
    if not sub_accounts or not root_account_id:
        root_account_id = stsc.get_caller_identity()['Account']
        sub_accounts = [subacc for subacc in orgs.list_accounts()['Accounts'] if subacc.get('Id') != root_account_id]


def get_assumed_session(sub_account_id):
    role_arn = f'arn:aws:iam::{sub_account_id}:role/{iam_reader_role_name}'
    creds = stsc.assume_role(RoleArn=role_arn, RoleSessionName='sso_role_sync')['Credentials']
    return Session(aws_access_key_id=creds['AccessKeyId'], aws_secret_access_key=creds['SecretAccessKey'],
                   aws_session_token=creds['SessionToken'])


def get_filtered_saml_providers(assumed_session):
    sub_iam = assumed_session.client('iam')
    # print(sub_iam.list_saml_providers())
    saml_provider_arns = list()
    for prov in sub_iam.list_saml_providers()['SAMLProviderList']:
        provider_details = sub_iam.get_saml_provider(SAMLProviderArn=prov.get('Arn'))
        xml = et.fromstring(provider_details['SAMLMetadataDocument'])
        if xml.find(".").attrib["ID"] == saml_id and xml.find(".").attrib["entityID"] == saml_entity_id:
            saml_provider_arns.append(prov.get('Arn'))
    if len(saml_provider_arns) == 0:
        logger.warning("The list of filtered SAML providers is 0. This means that no role synchronization will take place.")
    return saml_provider_arns


def get_trusted_roles(assumed_session, saml_provider_arns):
    saml_roles = dict()
    sub_iam = assumed_session.client('iam')
    roles = sub_iam.list_roles()['Roles']
    for role in roles:
        if 'AssumeRolePolicyDocument' in role:
            statements = [stmt for stmt in role['AssumeRolePolicyDocument']['Statement'] if stmt.get('Action') == 'sts:AssumeRoleWithSAML']
            if len(statements) == 1 and statements[0]['Principal']['Federated'] in saml_provider_arns:
                prov_arn = statements[0]['Principal']['Federated']
                if prov_arn not in saml_roles:
                    saml_roles[prov_arn] = list()
                saml_roles[prov_arn].append(role.get('Arn'))
    return saml_roles


def process_accounts():
    for subid in [sid.get('Id') for sid in sub_accounts]:
        assumed_session = get_assumed_session(subid)
        saml_provider_arns = get_filtered_saml_providers(assumed_session)
        #print(f'filtered saml provider --> {saml_provider_arns}')
        roles_for_providers = get_trusted_roles(assumed_session, saml_provider_arns)
        # print(sub_iam.get_available_subresources())
        # saml_provider = sub_iam.SamlProvider('arn')
        connector = importlib.import_module(saml_connector)
        connector.handle(roles_for_providers)


def handler(event, context):
    logger.info(event)
    logger.info(context)
    if not saml_entity_id or not saml_id or not sso_app_id:
        init_params()
    cache_accounts()
    process_accounts()
    # azure_handler(event, context)
    # print(get_accounts())
    return make_response(200, 'OK')


