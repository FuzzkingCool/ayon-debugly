# Notion Integration Setup Guide

This guide will help you set up the Notion integration for Debugly to automatically create issues in your Notion database.

## Prerequisites

1. A Notion account with access to create integrations
2. A Notion database for tracking issues and bugs
3. AYON server with Debugly addon installed
4. Access to AYON server settings and secrets management

## Step 1: Create a Notion Integration

1. Go to [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click "New integration"
3. Give your integration a name (e.g., "Debugly Issue Tracker")
4. Select the workspace where your database is located
5. Click "Submit"
6. Copy the **Internal Integration Token** - you'll need this later

## Step 2: Get Your Database ID

1. Open your Issues & Bugs database in Notion
2. Look at the URL in your browser
3. The URL format is: `https://www.notion.so/{workspace}/{database_id}?v=...`
4. Copy the `database_id` part (it's a 32-character string, may or may not include dashes)

**Note**: The Debugly integration automatically handles database ID formatting, so you can use either:
- Compact format: `a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6`
- UUID format: `a1b2c3d4-e5f6-g7h8-i9j0-k1l2m3n4o5p6`

## Step 3: Share Your Database with the Integration

1. Open your database in Notion
2. Click the "Share" button in the top right
3. Click "Invite" and search for your integration name
4. Select your integration and click "Invite"
5. Make sure the integration has "Can edit" permissions

## Step 4: Configure AYON Server Settings

The Notion integration is configured through AYON server settings, not environment variables.

### 4.1 Add Notion API Key to AYON Secrets

1. In your AYON server, go to **Settings > Studio > Secrets**
2. Click "Add Secret"
3. Set the secret name to `notion_debugly` (or any name you prefer)
4. Set the secret value to your Notion integration token from Step 1
5. Save the secret

### 4.2 Configure Debugly Settings

1. In your AYON server, go to **Settings > Addons > Debugly**
2. Expand the **Endpoints** section
3. Expand the **Notion** subsection
4. Configure the following settings:

#### Required Settings:
- **Enabled**: Check this to enable the Notion endpoint
- **Database ID**: Enter your Notion database ID from Step 2
- **API Key**: Select the secret name you created (e.g., `notion_debugly`)

#### Optional Settings:
- **Assignee ID**: Enter the Notion user ID of who should be assigned to new issues (optional)

## Step 5: Database Schema Requirements

Your Notion database should have the following properties (columns):

### Required Properties

- **Title** (type: Title) - This is required for all Notion databases
  - The integration will automatically use the first title property found
  - If no title property exists, it will fall back to using "Title"

### Optional Properties

The integration will automatically detect and use these properties if they exist:

- **Status** (type: Select) - For tracking issue status
  - The integration will try to set this to "Backlog if available
  - If "Backlog" is not available, it will use the first option in the list

- **Priority** (type: Select) - For setting issue priority
  - The integration will try to find options containing "P0", "P1", "P2", or "P3"
  - If no priority options are found, it will use the first option in the list

- **Tags** (type: Multi-select) - For categorizing issues
  - Currently not used by the integration but supported

- **Assign** (type: People) - For assigning issues to team members
  - Will be set if you configure an assignee_id in the settings

- **Submitted By** (type: People) - For tracking who submitted the issue
  - Automatically set to the current user's Ayon full name
  - The user must exist in your Notion workspace for this to work
  - If the user is not found, this field will be left empty

- **Attachments** (type: Files) - For file attachments
  - The integration will automatically upload and attach files to this field

### Recommended Select Options

#### Status Options
- Backlog
- Ready To Start
- In progress
- Done

#### Priority Options
- P0 (Critical)
- P1 (High)
- P2 (Medium)
- P3 (Low)

## Step 6: Test the Integration

1. Open the Debugly application from your AYON launcher
2. Create a test issue with:
   - A title
   - A description
   - Some attachments (optional)
3. Submit the issue
4. Check your Notion database for the new page

If successful, you should see:
- A new page created in your Notion database
- The page title set to your issue title
- The issue description in the page content
- Any attachments uploaded and linked
- System information and collected data in the page content

## Step 7: Integration Features

When an issue is submitted through Debugly, the Notion integration will:

1. **Create a new page** in your Notion database
2. **Set database properties**:
   - Title: The issue title
   - Status: "Backlog" (if available)
   - Priority: Based on available options
   - Assign: The configured assignee (if set)
   - Submitted By: The current user's Ayon full name (if user exists in workspace)
3. **Add detailed content** including:
   - Issue description with markdown support
   - Collected system data (environment, OS info, etc.)
   - Error details and stack traces
   - Timestamp information
   - Attachment information
4. **Upload attachments**:
   - Screenshots
   - Log files (converted to .txt for Notion compatibility)
   - Other attached files
5. **Parse markdown links** in the issue description to create clickable links

## Troubleshooting

### Common Issues

1. **"Notion endpoint is not enabled in settings"**
   - Make sure you've enabled the Notion endpoint in AYON server settings
   - Check that the "Enabled" checkbox is checked in Debugly > Endpoints > Notion

2. **"Notion API key secret name is required in settings"**
   - Make sure you've created a secret in AYON with your Notion API key
   - Verify that the secret name matches what you've configured in the settings

3. **"Failed to retrieve Notion API key from secret"**
   - Check that the secret exists and contains the correct Notion integration token
   - Verify the secret name is correct in the Debugly settings

4. **"Notion database ID is required in settings"**
   - Make sure you've entered the correct database ID in the Debugly settings
   - Verify the database ID is correct and the integration has access to it

5. **"Failed to create Notion page: 403"**
   - Make sure your integration has been invited to the database
   - Check that the integration has "Can edit" permissions
   - Verify the integration token is correct and not expired

6. **"Failed to create Notion page: 400"**
   - Check that your database has a "Title" property (required)
   - Verify that select options match exactly (case-sensitive)
   - Check the Notion API documentation for the latest requirements

7. **"Submitted By field is not being set"**
   - Make sure the user exists in your Notion workspace
   - Verify that the user's full name in Ayon matches their name in Notion
   - Check that the user has been invited to the workspace
   - The integration will log warnings if users are not found

8. **Attachments fail with Cloudflare HTML (HTTP 403, "Attention Required!")**

   This is **not** the same as a Notion JSON `403` (permissions / workspace limits).

   - **Symptom:** The Notion issue **page is created**, but attachment upload fails. The error body is HTML mentioning Cloudflare and "unable to access notion.com", not a JSON `code` like `restricted_resource`.
   - **Cause:** The File Upload **send** step (`POST …/file_uploads/…/send`, multipart) was blocked at the network edge — often log content in debug `.txt` files, multipart POST shape, or the **AYON server egress IP** (uploads run server-side via `notion/attach_bundle`, not on the artist workstation).
   - **Fallback:** If Debugly Shared Folder is configured, the full report ZIP is still saved there; the Notion page note mentions this.
   - **Diagnose from the AYON server host** (same network as outbound Notion calls):

     ```powershell
     cd path\to\ayon-debugly
     # .env with NOTION_API_KEY and NOTION_DB_ID
     python scripts/test_notion_upload.py --small-only
     python scripts/test_notion_upload.py --repro-failing-names
     python scripts/test_notion_upload.py --probe-upload-hosts
     ```

     - `--probe-upload-hosts` logs `raw_upload_host`, `send_host`, and `cf-ray` without sending file bytes (safe first check on server).
     - Small upload OK, repro names fail → content/WAF sensitivity (not API version).
     - Everything fails from server, OK from dev PC → server IP or outbound path; adjust egress or contact Notion with `cf-ray` from server logs.
   - **Server logs:** Look for `url_host=` / `send_host=` on Notion upload lines; Cloudflare blocks include `cf-ray` in the error summary.

9. **Free workspace 5 MiB attachment limit**

   Notion free workspaces cap uploads at 5 MiB per file. Larger attachments return Notion JSON errors (not Cloudflare HTML). The test script logs workspace limits via `GET /workspace`:

   ```powershell
   python scripts/test_notion_upload.py --small-only
   ```

### Getting Help

If you encounter issues:

1. Check the Notion API documentation: [https://developers.notion.com/](https://developers.notion.com/)
2. Verify your integration settings at [https://www.notion.so/my-integrations](https://www.notion.so/my-integrations)
3. Check the Debugly logs for detailed error messages
4. Ensure your AYON server has the latest version of the Debugly addon

## Security Notes

- Keep your Notion integration token secure
- Use AYON's secrets management system to store the API key
- The token has access to any databases you share with the integration
- Regularly rotate your integration tokens for security
- Consider using different integrations for different environments (dev/staging/prod)

## API Limits

Notion has rate limits for API calls:
- 3 requests per second for integrations
- 1000 requests per minute for integrations

The Debugly integration is designed to be efficient and should not hit these limits under normal usage.

## Advanced Configuration

### Custom Database Properties

The integration automatically adapts to your database schema. If you want to add custom properties:

1. Add the property to your Notion database
2. The integration will automatically detect and use it if it matches the expected types
3. Check the Debugly logs to see which properties are being used

### File Upload Support

The integration supports uploading various file types:
- Images: PNG, JPG, JPEG, GIF
- Documents: PDF, TXT, MD, CSV, JSON
- Log files: Automatically converted to .txt for Notion compatibility

### Markdown Support

The integration includes markdown parsing for:
- Links: `[text](url)` are converted to clickable Notion links
- Basic formatting: Bold, italic, headings, lists
- The integration ensures URLs have proper `https://` prefixes 