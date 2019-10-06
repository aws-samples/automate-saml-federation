#!/usr/bin/env bash

# A bash script to store Azure Access Parameters in AWS SSM Property Store;
# It will require the Azure Tenant Name, Enterprise (SSO) Application Owner's user and pass and the application id;
# It will connect to Azure, verify the authentication parameters and download the rest of the information.
# Additionally you will need the Metadata file.

# Required utilities to be installed in your environment: aws cli, xmllint, jq, curl

#Usage: ./xtract_azure_properties.sh PATH_TO_METADATA_FOLDER [AWS_CLI_PROFILE_NAME]

DEBUG=false
AWS=$(which aws)
LINT=$(which xmllint)
JQ=$(which jq)
PUT="${AWS} ssm put-parameter --overwrite"
PROFILE=""
CURL=$(which curl)
CLIENT_ID="1950a258-227b-4e31-a9cf-717495945fc2"
APP_OBJ_ID=null

debug() {
    [[ "${DEBUG}" = true ]] && >&2 echo -e "D: \033[33m ${1} \033[0m"
}

put_param(){
    TYPE=$([[ ! -z "$3" ]] && echo "$3" || echo "String")
    V_NAME=$1
    V_VALUE=$2
    JSON_STRING=$(${JQ} -n \
                  --arg n "${V_NAME}" \
                  --arg t "${TYPE}" \
                  --arg v "${V_VALUE}" \
                  '{Name: $n, Type: $t, Value: $v}' )
    debug "\033[33m${PUT} --cli-input-json ${JSON_STRING} ${PROFILE} \033[0m"
    RES=$(${PUT} --cli-input-json "${JSON_STRING}" ${PROFILE})
    [[ $? -ne 0 ]] && >&2 echo -e "\033[31mFailed to put parameter ${V_NAME} due to ${RES} \033[0m" && exit -1 || echo -e "\033[32m ${V_NAME} successfully placed as ${TYPE} \033[0m"
    debug ${RES//\\n/}
}

get_unique_file_for_extension(){
    FOLDER=${1}
    FILE_PATTERN=${2}
    debug "Searching in ${FOLDER} for ${FILE_PATTERN}"
    RES=$(find ${FOLDER} -name "${FILE_PATTERN}")
    [[ $? -ne 0 ]] && >&2 echo -e "\033[31m Pattern [${FILE_PATTERN}] could not be found in ${FOLDER}! Working dir: $(pwd) \033[0m" && exit -1
    debug "Files\n${RES}"
    CNT=$(echo "${RES}"|wc -l)
    HITS=${CNT//[[:blank:]]/}
    if [[ ${HITS} -gt 1 ]]; then
        read -p "More than one file with pattern ${FILE_PATTERN} was found. Please specify the one you need: "  FILE
        echo "${FOLDER}/${FILE}"
    elif [[ ${HITS} -eq 0 ]]; then
        >&2 echo -e "\033[31m Required pattern ${FILE_PATTERN} couldn't be found in folder ${FOLDER} \033[0m"
        exit -1
    else
        echo ${RES}
    fi
}

authenticate(){
    USER=$1
    PASS=$2
    TENANT=$3
    URL="https://login.microsoftonline.com/${TENANT}/oauth2/token"
    RES=$(${CURL} -X POST -s -d resource='https://graph.microsoft.com' -d client_id=${CLIENT_ID} -d grant_type=password -d username=${USER} -d password=${PASS} -d scope=openid -d scp='User.ReadBasic.All; User.Read.All; User.ReadWrite.All; Directory.Read.All; Directory.ReadWrite.All; Directory.AccessAsUser.All' "${URL}")
    ERR_CODE=$?
    debug "Authentication Result: ${RES}"
    [[ ${ERR_CODE} -ne 0 ]] && >&2 echo -e "\033[31m Error while authenticating: ${RES} \033[0m" && exit -1
    ERR_CODE=$(echo ${RES}|${JQ} '.error')
    [[  ${ERR_CODE//\"} -ne 'null' ]] &&  >&2 echo -e "\033[31m ${ERR_CODE//\"} while authenticating \033[0m" || TKN=$(echo ${RES}|${JQ} '.access_token') && debug "TOKEN: ${TKN//\"}"; echo ${TKN//\"}
}

get_msiam_access_id() {
    TENANT=$1
    APP_ID=$2
    TOKEN=$3
    URL="https://graph.microsoft.com/beta/${TENANT}/applications/${APP_ID}"
    debug "Request URL ${URL}"
    RES=$(${CURL} -s -H "Authorization: Bearer ${TOKEN}" -H "Accept: application/json"  "${URL}")
    ERR_CODE=$?
    debug "Result: ${RES}"
    # >&2 echo -e "\033[33m RESULT STRING ${RES} \033[0m"
    [[ ${ERR_CODE} -ne 0 ]] && >&2 echo -e "\033[31m Error while retrieving stuff \033[0m" && exit -1
    ERR_CODE=$(echo ${RES}|${JQ} '.error')
    [[ ${ERR_CODE//\"} -ne 'null' ]] &&  >&2 echo -e "\033[31m ${ERR_CODE//\"} while extracting msiam id \033[0m" || MSID=$(echo ${RES}|${JQ} '.appRoles[] |select(.description == "msiam_access") | .id') && echo ${MSID//\"}
}

process_metadata_vars(){
    METADATA=$(get_unique_file_for_extension "$1" "*.xml")
    [[ -z "${METADATA}" ]] && echo "Metadata file couldn't be found" && exit -1
    echo "Reading metadata file: [${METADATA}]"
    entityId=$(${LINT} --noblanks --xpath 'string(//@entityID)' "${METADATA}")
    [[ $? -ne 0 ]] && >&2 echo "Couldn't extract [entityId]" && exit -1
    Id=$(${LINT} --noblanks --xpath 'string(//@ID)' "${METADATA}")
    [[ $? -ne 0 ]] && >&2 echo "Couldn't extract [ID]" && exit -1
    # echo "Saving [${ID}] as saml_id"
    put_param "iam-saml.saml_id" "${Id}"
    # echo "Saving [${entityId}] as saml_entity_id"
    put_param "iam-saml.saml_entity_id" "${entityId}"
}

process_manifest_vars(){
    MANIFEST=$(get_unique_file_for_extension "$1" "*.json")
    [[ -z "${MANIFEST}" ]] && echo "Manifest file couldn't be found" && exit -1
    debug "MANIFEST FILE: ${MANIFEST}"
    APP_OBJ_ID=$(${JQ} '.id' ${MANIFEST})
    APP_OBJ_ID=${APP_OBJ_ID//\"}
    put_param "iam-saml.app_object_id" "${APP_OBJ_ID}"
    [[ ${APP_OBJ_ID} -eq 'null' ]] && >&2 echo -e "\033[31m SSO Application Object ID not found \033[0m" && exit -1
}

set_params(){
    read -p $'\033[32m Azure AD Tenant Name: \033[0m' TENANT
    read -p $'\033[32m Enter Enterprise Application Owner User: \033[0m'  USER
    read -s -p $'\033[32m Enter Enterprise Application Owner Password: \033[0m'  PASS
    echo ''

    TOKEN=$(authenticate ${USER} ${PASS} ${TENANT})
    [[ -z ${TOKEN} ]] && >&2 echo -e "\033[31m Authentication unsuccessful \033[0m" && exit -1
    [[ ${TOKEN} -eq 'null' ]] && >&2 echo -e "\033[31m Authentication unsuccessful \033[0m" && exit -1

    JSON_STRING=$( ${JQ} -n \
                  --arg u "${USER}" \
                  --arg p "${PASS}" \
                  '{AzureUser: $u, AzurePassword: $p}' )
    MSIAM_ACCESS_ID=$(get_msiam_access_id "${TENANT}" "${APP_OBJ_ID}" "${TOKEN}")
    [[ -z ${MSIAM_ACCESS_ID} ]] && >&2 echo -e "\033[31m MSIAM ACCESS ID extraction unsuccessful \033[0m" && exit -1
    put_param "iam-saml.secret" "${JSON_STRING}" SecureString
    put_param "iam-saml.tenant_name" "${TENANT}"
    put_param "iam-saml.msiam_access_id" "${MSIAM_ACCESS_ID}"

}

init() {
    [[ $# -eq 0 ]] && echo "Please provide the config folder as an argument for the script." && exit -1
    [[ -z "${AWS}" ]] && echo "aws cli needs to be installed" && exit -1
    [[ -z "${LINT}" ]] && echo "xml lints needs to be installed" && exit -1
    [[ -z "${JQ}" ]] && echo "jq needs to be installed" && exit -1
    [[ -z "${CURL}" ]] && echo "curl needs to be installed" && exit -1
    [[ ! -d "${1}" ]] && echo -e "\033[31mThe provided config folder (${1}) does not exists or not readable. Exiting. \033[0m" && exit -1
    [[ ! -z "${2}" ]] && echo "Using profile: [${2}]" && PROFILE="--profile ${2}"
    # DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
    # cd ${DIR}
}

init "${1}" "${2}"
process_metadata_vars "${1}"
process_manifest_vars "${1}"
set_params

