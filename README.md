# About:

This is a sample solution to integrate multiple AWS Organization Member accounts with a 3rd party SAML provider for SSO.
It provides a Lambda function which can be scheduled to run at specific intervals by CloudWatch and which will visit all the member accounts of an AWS Organizations, read all the Roles
which do trust a specific SAML IDP Provider and synchronize it with the Provider.
Currently there is one single Provider Synchronizer implementation with Microsoft Azure, but the solution can be easily extended in the future.

It provides two components, packaged into a single function:
- the main APP, which can be scheduled from CloudWatch and will collect all Roles trusting a selected SAML provider;
- azure_sync which will synchronize the collected roles with Azure AD via the Graph (Rest Api);

The function reads all parameters from System Manager's Property Store.

Additionally there are a set of CloudFormation Templates which will:
- inject [2 roles in all Member Accounts](./cfn_templates/cross_account_access_for_invited_members.yaml) in an AWS Organization in order to execute activities from the root account in the member accounts
- create a [role in the root account](./cfn_templates/root_account_stackset_admin.yaml) for executing CloudFormation templates in CloudStack in a centralized way
- install the [SAML providers altogether with standardized roles](./cfn_templates/saml-roles.yaml) in the member accounts
- additionally a role with limited access to IAM service to read the roles, which can be used by the Lambda function

This solution is loosely based on the original work described in this [blog](https://aws.amazon.com/blogs/security/how-to-automate-saml-federation-to-multiple-aws-accounts-from-microsoft-azure-active-directory/)
and these [powershell scripts](https://github.com/awslabs/aws-iam-aad);


## Requirements
* AWS CLI already configured with Administrator permission
* [Python 3 installed](https://www.python.org/downloads/)
* [Docker installed](https://www.docker.com/community-edition)
* Administrative access to the root account of an AWS Organization;
* Admisnistrative access to all the member accounts of an AWS Organization;
* [Azure SSO Enterprise Application Setup](./docs/azure_setup.md)

## Setup process

This guide relies on the use of CloudFormation stack set, which is a centralized way of running CloudFormation templates in 
multiple member accounts. First we need to prepare the organization:
- add the AWSCloudFormationStackSetAdministrationRole and AWSCloudFormationStackSetExecutionRole to the root account;
- and the role AWSCloudFormationStackSetExecutionRole to **all** of the member accounts;

Once this step is ready we need to set up our SAML provider. This template takes Azure as an SSO/Sampl Provider sample implementation. The guide to set it up can be found [here](./docs/azure_setup.md).

As soon as we have the METADATA file from the SAML provider, it comes the "pièce de résistance", which is composed of:
- an [IAM Reader Role](./cfn_templates/member_iam_access_role.yaml) which is deployed in all of the member accounts and later will be be assumed by the Lambda function running in the root account;
- an [set of standardized roles and an IDP provider](./cfn_templates/saml-roles.yaml) which will be deployed in each and every member account;

### Prepare the root account for executing Stackset instances in each and every member account
Let's prepare the root account so that to be able to execute Stack Sets:
```bash
aws cloudformation create-stack --stack-name stackset-admin-role \
--capabilities CAPABILITY_NAMED_IAM --profile root-org \
--template-body file://./cfn_templates/root_account_stackset_admin.yaml
```
*Please note:* you need to replace the "root-org" with the name of the AWS CLI profile name of your AWS Account, which represents the AWS Organization's Root Account.
Check the execution status:
```bash
aws cloudformation describe-stacks --stack-name stackset-admin-role \
--profile root-org --query 'Stacks[0].StackStatus'
```

### Prepare the member accounts

Run the following command once for every member account, using the member credentials (replace the "xxxxyyyyy" with the ID of the root account)
```bash
aws cloudformation create-stack --stack-name cross-account-access-roles \ 
--parameters ParameterKey=TrustedAccountNumber,ParameterValue=xxxxyyyyy \
--capabilities CAPABILITY_NAMED_IAM --profile member1 \
--template-body file://./cfn_templates/cross_account_access_for_invited_members.yaml
```
*Please Note:* the "member1" string needs to be changed to the name of the profile your member account;

Wait until the following command returns **"CREATE_COMPLETE"**:
```bash
aws cloudformation describe-stacks --stack-name cross-account-access-roles \ 
--profile member1 --query 'Stacks[0].StackStatus'
```

In case something goes wrong you might want to check the details with:
```bash
aws cloudformation describe-stack-events \
--stack-name cross-account-access-roles \
--profile member1 \
--query 'StackEvents[*].[ResourceType,ResourceStatus,ResourceStatusReason]' \
--output text|column -s $'\t' -t
```

Repeat these steps with all member accounts which were invited (and not created) in your organization.
Once finished, we are ready to use the CloudFormation StackSet to roll out unified configurations in our organization.

### Add IAM Access Role to all accounts using CloudFormation Stacks

At this step we will create a new stack set which will deploy a restricted role, called AWS_IAM_AAD_UpdateTask_CrossAccountRole used by the role synchronizing lambda function in a later step (please not: **"xxxxyyyyy"** is the account number of your root account).

```bash
aws cloudformation create-stack-set --stack-set-name member-iam-access-role --profile root-org \
--parameters ParameterKey=TrustedAccountNumber,ParameterValue=xxxxyyyyy \
--capabilities CAPABILITY_NAMED_IAM \
--template-body file://./cfn_templates/member_iam_access_role.yaml
```
Wait until the following command returns **"Active"** for a stack set name "member-iam-access-role":
```bash
aws cloudformation list-stack-sets --profile root-org
```
or
```bash
aws cloudformation list-stack-sets --profile root-org --query "Summaries[?(@.StackSetName=='member-iam-access-role')].Status | [0]"
```

### Create the IDP providers and a set of initial roles in every organization

Create the necessary roles in all accounts:
```bash
aws cloudformation create-stack-instances --stack-set-name member-iam-access-role \ 
--profile root-org --accounts '["xxxxxxyyyyyy","yyyyzzzzzzz"]' \ 
--regions '["eu-west-1"]' --operation-preferences FailureToleranceCount=0,MaxConcurrentCount=1 \
--query 'OperationId'
```
where "xxxxxxyyyyyy" is the root account, "yyyyzzzzzzz" is one of the member accounts and the list is continued with all member accounts.
Check the execution result (use the ID returned in the previous step as a parameter:
```bash
aws cloudformation describe-stack-set-operation \ 
--stack-set-name member-iam-access-role --profile root-org \ 
--operation-id xxx-yyyy-zzzzzz --query 'StackSetOperation.Status'
```
If you see "RUNNING", wait until it turns into "FAILED" or "SUCCEEDED". If failed, check the status with:
```bash
aws cloudformation list-stack-instances --profile root-org --stack-set-name member-iam-access-role
```
Now let's add a bit of bash-magic and add the SAML metadata to our final CloudFormation template. At this step the SAML provider (eg. Azure Enterprise Application) needs to be set up already.
The metadata.xml is the SAML file downloaded in a previous step from the SAML Provider (Azure in this case).
```bash
sed -e "s/<MetadataDocument>/$(sed 's:/:\\/:g' ./metadata.xml)/" cfn_templates/saml-roles.yaml > cfn_templates/saml-roles-out.yaml
```
>>>
```bash
aws cloudformation create-stack-set --stack-set-name saml-providers-and-roles --profile root-org \
--capabilities CAPABILITY_NAMED_IAM \
--template-body file://./cfn_templates/saml-roles-out.yaml
```
>>>
```bash
aws cloudformation list-stack-sets --profile root-org --query "Summaries[?(@.StackSetName=='saml-providers-and-roles')].Status | [0]"
```
If Active we can install the IDP/SAML provider in all accounts.
```bash
aws cloudformation create-stack-instances --stack-set-name saml-providers-and-roles \
--profile root-org --accounts '["xxxxxxyyyyyy","yyyyzzzzzzz"]' \
--regions '["eu-west-1"]' --operation-preferences FailureToleranceCount=0,MaxConcurrentCount=1 \
--query 'OperationId'
```
Check the results (you should see SUCCEEDED):
```bash
aws cloudformation describe-stack-set-operation \
--stack-set-name saml-providers-and-roles --profile root-org \
--operation-id 17d21f5c-1a92-480f-9ac5-37ffeb30e60d --query 'StackSetOperation.Status'
```
## Deploying the role synchronizing lambda function

Let's put the cherry on the cake.

The following command builds the lambda function and will run it on your local computer:
```bash
sam build && sam local invoke "RoleSyncFunction" -e schedule_evt.json --profile root-org --region eu-west-1
```
### Now let's deploy it
Firstly, we need a `S3 bucket` where we can upload our Lambda functions packaged as ZIP before we deploy anything - If you don't have a S3 bucket to store code artifacts then this is a good time to create one:

```bash
aws s3 mb s3://role-sync-lmbda --profile root-org
```

Next, run the following command to package our Lambda function to S3:

```bash
sam package \
--output-template-file packaged.yaml \
--s3-bucket role-sync-lmbda --profile root-org
```
Next, the following command will create a Cloudformation Stack and deploy your SAM resources.
```bash
sam deploy \
--template-file packaged.yaml \
--stack-name role-sync-func \
--capabilities CAPABILITY_IAM --profile root-org
```

> **See [Serverless Application Model (SAM) HOWTO Guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-quick-start.html) for more details in how to get started.**

After deployment is complete you can run the following command to retrieve the API Gateway Endpoint URL:

## Fetch, tail, and filter Lambda function logs

To simplify troubleshooting, SAM CLI has a command called sam logs. sam logs lets you fetch logs generated by your Lambda function from the command line. In addition to printing the logs on the terminal, this command has several nifty features to help you quickly find the bug.

`NOTE`: This command works for all AWS Lambda functions; not just the ones you deploy using SAM.

```bash
sam logs -n -RoleSyncFunction -stack-name role_sync --tail
```

You can find more information and examples about filtering Lambda function logs in the [SAM CLI Documentation](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-logging.html).

## Cleanup

In order to delete our Serverless Application recently deployed you can use the following AWS CLI Command:

```bash
aws cloudformation delete-stack --stack-name role_sync
```


