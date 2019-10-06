## Step 1: Configure Microsoft Azure Active Directory

We need a User dedicated for the integfration and a new SSO Enterprise application. 

### Create integration user 
1. Open Azure Portal.
2. Open Azure Active Directory.
3. In the left pane, select Users.
4. In the Manage pane, select All users.
5. Select New user.
6. Enter values for the Name and User name fields.
7. Select the Show Password box and note the auto-generated password for this user. You will need it when you change the password.
8. Select Create.
9. Open a browser window and go to https://login.microsoftonline.com.
10. Log in with the new user. You’ll be prompted to change your password. Note the new password so you don’t forget it.

### Create enterprise application

1. Open Azure Portal.
2. Open Azure Active Directory.
3. In the Manage pane, select Enterprise applications.
4. Select New application.
5. In the gallery text box, type AWS.
6. You’ll see an option with the name Amazon Web Services (AWS). Select that application. Make sure you don’t choose the other option with the name “AWS Console.” That option uses an alternate integration method that isn’t relevant to this post.
7. Select Add. You can change the name to any name you would prefer.
8. Open the application using this path: Azure Portal > Azure Active Directory > Enterprise Applications > All Applications > your application name (for example, “Amazon Web Services (AWS)”).
9. From left pane, select Single Sign-on, and then set Single Sign-on mode to SAML-based Sign-on.
10. The first instance of the app is pre-integrated with Azure AD and requires no mandatory URL settings. However, if you previously created a similar application, you’ll see "Identifier )Entity ID): REQUIRED";
11. If you see the red “Required” value in the Identifier field, select the Edit button and enter a value for it. This can be any value you prefer (the default is https://signin.aws.amazon.com/saml), but it has to be unique within your Azure AD tenant. If you don’t see the Identifier field, it means it’s already prepopulated and you can proceed with the default value. However, if for any reason you prefer to have a custom Identifier value, you can select the Show advanced URL settings checkbox and enter the preferred value.
12. In the User Attributes section, select the Edit button.
13. You need to tell Azure AD what SAML attributes and values are expected and accepted on the AWS side. AWS requires two mandatory attributes in any incoming SAML assertion. The Role attribute defines which roles the federated user is allowed to assume. The RoleSessionName attribute defines the specific, traceable attribute for the user that will appear in AWS CloudTrail logs. Role and RoleSessionName are mandatory attributes. You can also use the optional attribute of SessionDuration to specify how long each session will be valid until the user is requested to get a new token. Add the following attributes to the User Attributes & Claims section in the Azure AD SSO application. You can also remove existing default attributes, if you want, because they’ll be ignored by AWS:

| Name (case-sensitive) |	Value |	Namespace (case-sensitive)	| Required or optional? |
|-----------------------|---------|-----------------------------|-----------------------|
|RoleSessionName	|user.userprincipalname (this will show logged in user ID in AWS portal, if you want user name, replace it with user.displayName)|https://aws.amazon.com/SAML/Attributes|Required| 
|Role|user.assignedroles|https://aws.amazon.com/SAML/Attributes|Required|
|SessionDuration|An integer (within quotation marks) between 900 seconds (15 minutes) and 43200 seconds (12 hours).|https://aws.amazon.com/SAML/Attributes|Optional|

14. As a good practice, when it approaches its expiration date, you can rotate your SAML certificate. For this purpose, Azure AD allows you to create additional certificates, but only one certificate can be active at a time. In the SAML Signing Certificate section, make sure the status of this certificate is Active, and then select Federation Metadata XML to download the XML document.
15. Download the Metadata XML file and save it in the setup directory of the package you downloaded in the beginning of this walkthrough. Make sure you save it with file extension of .xml.
16. Open Azure Portal > Azure Active Directory > App Registrations > your application name (for example, “Amazon Web Services (AWS)”). If you don’t see your application in the list on the App Registrations page, select All apps from the drop-down list on top of that page and search for it.
17. Select Manifest. All Azure AD applications are described as a JavaScript Object Notification (JSON) document called manifest. For AWS, this manifest defines all AWS to Azure AD role mappings. Later, we’ll be using automation to generate updates to this file.
18. Select Download to download the app manifest JSON file. Make sure you save it with file extension of .json.
19. Now, back on your registered app, select Settings.
20. In the Settings pane, select Owners.
21. Select Add owner and add the user you created previously as owner of this application. Adding the Azure AD user as owner enables the user to manipulate this object. Since this application is the only Azure AD resource owned by our user, it means we’re enforcing the principle of least privilege on Azure AD side.
At this point, we’re done with the initial configuration of Azure AD. All remaining steps will be performed in your AWS accounts.


## Step 2: Configure the Property Store in the AWS Root Account

Use the following command to configure the property store in the Root Account with the necessary parts.

```bash
./util/xtract_azure_properties.sh ../aws-iam-aad/setup/ root-account-profile
```

It should provide an output like:

```bash
Using profile: [root-account-profile]
Reading metadata file: [../aws-iam-aad/setup//AWS_SSO_Demo.xml]
 iam-saml.saml_id successfully placed as String
 iam-saml.saml_entity_id successfully placed as String
 Azure AD Tenant Name: staging.mycompany.com
 Enter Enterprise Application Owner User: aws-sso-integration@staging.mycompany.com
 Enter Enterprise Application Owner Password:
 iam-saml.secret successfully placed as SecureString
 iam-saml.tenant_name successfully placed as String
 iam-saml.msiam_access_id successfully placed as String
 iam-saml.appId successfully placed as String
```
