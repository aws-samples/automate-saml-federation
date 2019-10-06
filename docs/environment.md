Step by step dev

```bash
sam init --runtime python3.7 -o role_sync -n role_sync
```

Run it locally:

```bash
sam build
sam local invoke "RoleSyncFunction" -e schedule_evt.json --profile dh-console-root --region eu-west-1
```

Azure Role Management: https://aws.amazon.com/blogs/security/how-to-automate-saml-federation-to-multiple-aws-accounts-from-microsoft-azure-active-directory/

https://docs.microsoft.com/en-us/azure/active-directory/develop/active-directory-enterprise-app-role-management