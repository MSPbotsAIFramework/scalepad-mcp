# ScalePad MCP Server

An [MCP](https://modelcontextprotocol.io) server for the [ScalePad](https://www.scalepad.com)
APIs. One ScalePad API key gives an AI agent access to five products:

- **Core** (read-only): the unified view of an MSP's clients, contacts, members, sites,
  opportunities, hardware and SaaS assets, service contracts, tickets and integrations.
- **Lifecycle Manager**: client engagement and roadmaps - initiatives, goals, meetings, action
  items, assessments, deliverables, budgets, contracts, hardware lifecycle and warranties.
- **ControlMap**: compliance per client - risks, controls, evidence and evidence requests,
  governance, policies, procedures, frameworks, assessments and action items.
- **Backup Radar** (read-only): backup health and backup devices per client.
- **Quoter**: quotes and quote templates, line items, catalog items, categories, contacts and
  suppliers.

On explicit request the agent can also create, update, attach, publish and delete records.

- Transport: MCP Streamable HTTP at `POST /mcp`, health probe at `GET /health`
- Stateless and multi-tenant: the API key arrives on every request as an HTTP header and is
  never stored; all 381 tools are listed from the first `tools/list`
- Python 3.12, [uv](https://docs.astral.sh/uv/), FastMCP, httpx
- License: Apache-2.0, Copyright 2026 MSPbots.ai

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

| Header | Required | Type | Default | Allowed values | Description | Example |
|---|---|---|---|---|---|---|
| `X-ScalePad-Api-Key` | Yes | string | none | - | ScalePad API key | `your-api-key` |
| `X-ScalePad-Region` | No | string | `us` | `us`, `eu`, `ca`, `au` | Region the ScalePad account is provisioned in | `us` |
| `X-Quoter-Client-Id` | No | string | none | - | Accepted for compatibility and ignored (see below) | - |
| `X-Quoter-Client-Secret` | No | string | none | - | Accepted for compatibility and ignored (see below) | - |

Where to get them:

- Sign in to ScalePad as an **active Administrator** and open your personal **API keys** page,
  choose **New API key**, give it a name and expiry (default 2 years) and copy the secret key.
  The key stops working if the user is deactivated or loses the Administrator permission.
- Any paid ScalePad subscription unlocks the Core, Quoter and ControlMap APIs; Lifecycle
  Manager needs a higher subscription. Calls to a product without a subscription return HTTP
  402.
- The region is the one the account was provisioned in. ControlMap is served in every region;
  Backup Radar in US and EU; Core, Lifecycle Manager and Quoter only on the US edge, so those
  tools always call `api.scalepad.com`.
- Quoter is reached through the ScalePad API (`https://api.scalepad.com/quoter/...`) with the
  same API key, so no separate Quoter OAuth client is needed; the two Quoter headers are kept
  only so existing connections keep working.

How the key is sent to ScalePad: every call carries `x-api-key: <key>` to
`https://{api|eu.api|ca.api|au.api}.scalepad.com/{core|lifecycle-manager|controlmap|backup-radar|quoter}/...`.
Values that look like unresolved templates (`${...}`) are treated as missing.

A request to `/mcp` without the key gets HTTP 401. An unknown region does not block the request
(so `tools/list` works with any values); tool calls then return an `invalid_argument` error naming
the allowed regions.

## Tools

All tools return a JSON string. Most ids are strings (some ControlMap ids are integers).
List tools are cursor-paginated: `page_size` (1-200) and the `next_cursor` from the previous
response as `cursor`; `filter` takes `{field: value}` pairs that are sent as
`filter[field]=value`, and the accepted fields are listed in each tool's parameter description.
List tools whose API returns the whole list at once (no `page_size`) take optional `offset` and
`limit`; when a result is cut by the response size limit, call again with `offset` set to the
returned `next_offset` to continue right after the last record. `scalepad_lm_opportunities_list`,
`scalepad_lm_warranty_pricing_list`, `scalepad_lm_opportunity_create_fields_get` and
`scalepad_lm_ticket_create_fields_get` need `client_id` (the live API rejects calls without it),
so they return `invalid_argument` without calling ScalePad when it is missing.
Exports that return files (PDF, XLSX) come back as `{content_type, size_bytes, base64}` for
small files and as metadata only for larger ones.

`scalepad_navigate(domain)` lists one product's tools with their purpose, and `scalepad_status`
checks which of the five products (Core, Lifecycle Manager, ControlMap, Backup Radar, Quoter) the
key can reach. The table lists every tool; **read** tools change
nothing, **write** tools change live records, **destructive** tools delete and cannot be
undone.

| Tool | Kind | Purpose | Required |
|---|---|---|---|
| `scalepad_navigate` | read | List one product's tools | **domain** |
| `scalepad_status` | read | Check which products the key can reach | - |

### Core (24 tools)

| Tool | Kind | Purpose | Required |
|---|---|---|---|
| `scalepad_core_clients_list` | read | Get a detailed list of clients | - |
| `scalepad_core_clients_get` | read | Get a single client, identified by its unique ID | **id** |
| `scalepad_core_contacts_list` | read | Get a detailed list of contacts | - |
| `scalepad_core_contacts_get` | read | Get a single contact, identified by its unique ID | **id** |
| `scalepad_core_members_list` | read | Get a detailed list of members | - |
| `scalepad_core_members_get` | read | Get a single member, identified by its unique ID | **id** |
| `scalepad_core_opportunities_list` | read | Get a detailed list of opportunities | - |
| `scalepad_core_opportunities_get` | read | Get a single opportunity, identified by its unique ID | **id** |
| `scalepad_core_sites_list` | read | Get a list of client sites materialized from PSA location data | - |
| `scalepad_core_sites_get` | read | Get a single client site identified by its unique ID | **id** |
| `scalepad_core_hardware_assets_list` | read | Get a detailed list of hardware assets | - |
| `scalepad_core_hardware_assets_get` | read | Get a single hardware asset, identified by its unique ID | **id** |
| `scalepad_core_saas_assets_list` | read | Get a detailed list of SaaS assets | - |
| `scalepad_core_saas_assets_get` | read | Get a single SaaS asset, identified by its unique ID | **id** |
| `scalepad_core_saas_users_list` | read | Get a detailed list of SaaS users | - |
| `scalepad_core_saas_users_get` | read | Get a single SaaS user, identified by its unique ID | **id** |
| `scalepad_core_product_catalog_list` | read | Get product catalog records exported from PSA integrations | - |
| `scalepad_core_product_catalog_get` | read | Get a single product catalog record, identified by its unique ID | **id** |
| `scalepad_core_integration_configurations_list` | read | Return the list of integration configurations associated with the MSP | - |
| `scalepad_core_integration_vendors_list` | read | Get a complete list of integration vendors which can be used to identify third-party services | - |
| `scalepad_core_contracts_list` | read | Get a detailed list of contracts | - |
| `scalepad_core_contracts_get` | read | Get a single contract, identified by its unique ID | **id** |
| `scalepad_core_tickets_list` | read | Get a detailed list of tickets | - |
| `scalepad_core_tickets_get` | read | Get a single ticket, identified by its unique ID | **id** |

### Lifecycle Manager (193 tools)

| Tool | Kind | Purpose | Required |
|---|---|---|---|
| `scalepad_lm_contacts_list` | read | List Lifecycle Manager contacts for accessible clients | - |
| `scalepad_lm_contacts_hidden_status_update` | write | Update whether a Lifecycle Manager contact is hidden | **contact_id**, **is_hidden** |
| `scalepad_lm_contacts_get` | read | Get a Lifecycle Manager contact by the contact's public ID | **contact_id** |
| `scalepad_lm_clients_lookup` | read | Search clients by name, returning a paged list of client id | - |
| `scalepad_lm_client_groups_lookup` | read | Find the Lifecycle Manager client groups a client belongs to | **client_key** |
| `scalepad_lm_client_members_lookup` | read | Search members | **client_id** |
| `scalepad_lm_clients_list` | read | Get paginated client summary by query parameter | - |
| `scalepad_lm_client_groups_list` | read | List all client groups for the authenticated partner account | - |
| `scalepad_lm_client_groups_get` | read | Get the details of a single client group, including its assigned users and clients | **client_group_id** |
| `scalepad_lm_client_groups_unassign` | write | Unassign clients and users from a client group | **client_group_id** |
| `scalepad_lm_client_groups_assign` | write | Assign clients and users to a client group | **client_group_id** |
| `scalepad_lm_client_contacts_lookup` | read | List Lifecycle Manager contacts for accessible clients | **client_id** |
| `scalepad_lm_active_users_list` | read | List the users that belong to the authenticated account, optionally including disabled users | - |
| `scalepad_lm_warranty_pricing_list` | read | List renewable warranty assets and their available monthly pricing options | - |
| `scalepad_lm_hardware_replacement_settings_get` | read | Get hardware replacement budget defaults by report asset type | - |
| `scalepad_lm_hardware_dashboard_get` | read | Get account- or client-scoped hardware totals, replacement due and soon counts | - |
| `scalepad_lm_hardware_overview_get` | read | Get a hardware asset overview for a hardware asset id or unique key, including summary | **hardware_key** |
| `scalepad_lm_hardware_list` | read | List hardware assets with client ownership and basic device fields | - |
| `scalepad_lm_hardware_lifecycles_list` | read | Get a list of active hardware lifecycle records from Lifecycle Manager | - |
| `scalepad_lm_hardware_attached_initiatives_lookup` | read | Get the initiatives attached to a hardware asset identified by its unique key | **hardware_key** |
| `scalepad_lm_hardware_attached_agreements_lookup` | read | List Hardware Asset Attached Agreements | **hardware_key** |
| `scalepad_lm_roadmap_spreadsheet_generate` | read | Generate a spreadsheet for a roadmap | **client_id** |
| `scalepad_lm_roadmap_pdf_generate` | read | Generate a pdf for a roadmap | **client_id** |
| `scalepad_lm_roadmap_csv_generate` | read | Generate a csv for a roadmap | **client_id** |
| `scalepad_lm_initiatives_status_update` | write | Change the current status of an initiative to reflect its progress in the business workflow | **id**, **status** |
| `scalepad_lm_initiatives_schedule_update` | write | Update the fiscal planning timeline for when resources will be allocated to this initiative | **id**, **fiscal_quarter** |
| `scalepad_lm_initiatives_recurring_update` | write | Manage the ongoing financial commitments of an initiative by updating the complete set of | **id**, **recurring_line_items** |
| `scalepad_lm_initiatives_priority_update` | write | Adjust the business priority level of an initiative to reflect its strategic importance | **id**, **priority** |
| `scalepad_lm_initiatives_budget_update` | write | Revise the complete financial plan for an initiative by providing a comprehensive breakdown of | **id**, **budget_line_items** |
| `scalepad_lm_initiatives_assigned_user_update` | write | Update the user assigned to an initiative | **initiative_id**, **assigned_user_id** |
| `scalepad_lm_initiatives_ticket_get` | read | Get the current state of the PSA ticket linked to an initiative | **initiative_id** |
| `scalepad_lm_initiatives_ticket_create` | write | Create a PSA ticket and link it to the initiative | **initiative_id**, **field_values** |
| `scalepad_lm_initiatives_ticket_detach` | write | Detach (unlink) the PSA ticket associated with an initiative | **initiative_id** |
| `scalepad_lm_initiative_templates_duplicate` | write | Duplicate an initiative template into a new account-scoped copy | **initiative_template_id** |
| `scalepad_lm_initiative_templates_get` | read | Get a specific initiative template by its unique identifier | **initiative_template_id** |
| `scalepad_lm_initiative_templates_update` | write | Update an account-scoped initiative template's name, summary, budget, recurring costs | **initiative_template_id**, **initiative_template** |
| `scalepad_lm_initiative_templates_delete` | destructive | Delete an account-scoped initiative template that is no longer needed | **initiative_template_id** |
| `scalepad_lm_initiative_templates_list` | read | Get all initiative templates available to the account, grouped by platform-provided | - |
| `scalepad_lm_initiative_templates_create` | write | Create a new account-scoped initiative template with budget, recurring costs, and action items | **initiative_template** |
| `scalepad_lm_initiatives_template_apply` | write | Apply an initiative template to an existing initiative, replacing its budget, recurring costs | **initiative_id**, **initiative_template_id** |
| `scalepad_lm_initiatives_quotes_list` | read | List all quotes linked to a specific initiative, along with status metadata | **initiative_id** |
| `scalepad_lm_initiatives_pdf_get` | read | Download a formatted PDF of an initiative, including its executive summary, budget | **initiative_id** |
| `scalepad_lm_initiatives_opportunity_get` | read | Get the PSA opportunity linked to an initiative | **initiative_id** |
| `scalepad_lm_initiatives_opportunity_create` | write | Create a PSA opportunity for an initiative and link it | **initiative_id**, **field_values** |
| `scalepad_lm_initiatives_opportunity_delete` | destructive | Detach the PSA opportunity associated with an initiative | **initiative_id** |
| `scalepad_lm_initiatives_opportunity_attach` | write | Attach an existing PSA opportunity to an initiative so the roadmap item is connected to revenue | **initiative_id**, **opportunity_id** |
| `scalepad_lm_initiatives_meetings_list` | read | Get the meetings that are aligned with a specific initiative | **initiative_id** |
| `scalepad_lm_initiatives_meetings_attach` | write | Attach an existing meeting to an initiative to establish alignment between client discussions | **initiative_id**, **meeting_id** |
| `scalepad_lm_initiatives_meetings_detach` | write | Detach a meeting and an initiative, without deleting either entity | **initiative_id**, **meeting_id** |
| `scalepad_lm_initiatives_list_v2` | read | Get a list of all strategic initiatives with filtering options | - |
| `scalepad_lm_initiatives_goals_list` | read | Get all goals that are aligned with a specific initiative | **initiative_id** |
| `scalepad_lm_initiatives_goals_attach` | write | Attach an existing goal to an initiative to establish alignment between strategic objectives | **initiative_id**, **goal_id** |
| `scalepad_lm_initiatives_goals_detach` | write | Detach a goal and an initiative, without deleting either entity | **initiative_id**, **goal_id** |
| `scalepad_lm_initiatives_get` | read | Access complete details of a specific initiative including its budget, recurring costs, status | **id** |
| `scalepad_lm_initiatives_update` | write | Partially update initiative details including name, description, internal visibility | **id** |
| `scalepad_lm_initiatives_delete` | destructive | Permanently remove an initiative that is no longer relevant to business operations | **id** |
| `scalepad_lm_initiatives_list` | read | Get a comprehensive list of all strategic initiatives with filtering options | - |
| `scalepad_lm_initiatives_create` | write | Create a new strategic initiative with all necessary details to establish a program, project | **client_key**, **name** |
| `scalepad_lm_initiatives_assets_detach` | write | Detach hardware assets from an initiative without deleting either entity | **initiative_id**, **hardware_keys** |
| `scalepad_lm_initiatives_assets_attach` | write | Attach one or more hardware assets to an initiative by hardware identifier | **initiative_id**, **hardware_keys** |
| `scalepad_lm_initiatives_action_items_list` | read | Get all action items that are aligned with a specific initiative | **initiative_id** |
| `scalepad_lm_initiatives_action_items_attach` | write | Attach an existing action item to an initiative to establish alignment between tasks | **initiative_id**, **action_item_id** |
| `scalepad_lm_initiatives_action_items_detach` | write | Detach an action item and an initiative, without deleting either entity | **initiative_id**, **action_item_id** |
| `scalepad_lm_goal_templates_get` | read | Get full details of a specific goal template | **goal_template_id** |
| `scalepad_lm_goal_templates_update` | write | Modify an existing account-owned goal template | **goal_template_id**, **goal_template** |
| `scalepad_lm_goal_templates_delete` | destructive | Delete an account-owned goal template that is no longer needed | **goal_template_id** |
| `scalepad_lm_goal_templates_list` | read | Get all goal templates visible to the authenticated account with optional title search | - |
| `scalepad_lm_goal_templates_create` | write | Create a new account-owned goal template | **goal_template** |
| `scalepad_lm_goals_status_update` | write | Change goal status to reflect its current state in the business workflow | **id**, **status** |
| `scalepad_lm_goals_schedule_update` | write | Update goal target period to reflect its current state in the business workflow | **id**, **target_period** |
| `scalepad_lm_goals_meetings_list` | read | Get all meetings that is aligned with this goal | **goal_id** |
| `scalepad_lm_goals_meetings_attach` | write | Attach an existing meeting to a goal to establish that this strategic objective will be | **goal_id**, **meeting_id** |
| `scalepad_lm_goals_meetings_detach` | write | Detach a meeting and a goal without deleting the meeting itself | **goal_id**, **meeting_id** |
| `scalepad_lm_goals_initiatives_list` | read | Get all initiatives that are aligned with this goal | **goal_id** |
| `scalepad_lm_goals_initiatives_attach` | write | Attach an existing initiative to a goal to establish a relationship between the strategic | **goal_id**, **initiative_id** |
| `scalepad_lm_goals_initiatives_detach` | write | Detach an initiative and a goal without deleting the initiative itself | **goal_id**, **initiative_id** |
| `scalepad_lm_goals_get` | read | Get a goal record in Lifecycle Manager by the goal's id | **id** |
| `scalepad_lm_goals_update` | write | Partially update goal details including title, rich-text description, status, target period | **id** |
| `scalepad_lm_goals_delete` | destructive | Delete a goal that is no longer relevant to business operations | **id** |
| `scalepad_lm_goals_create_from_template` | write | Create a new goal from an existing goal template | **goal_template_id**, **client_key** |
| `scalepad_lm_goals_list` | read | List all goals to help you quickly find relevant objectives with filtering options | - |
| `scalepad_lm_goals_create` | write | Create a new goal with all necessary details to establish a measurable objective | **client_key**, **title** |
| `scalepad_lm_goals_action_items_list` | read | Get all action items that are linked to this goal | **goal_id** |
| `scalepad_lm_goals_action_items_attach` | write | Attach an existing action item to a goal to track tasks that contribute toward the goal's | **goal_id**, **action_item_id** |
| `scalepad_lm_goals_action_items_detach` | write | Detach an action item from a goal without deleting either entity | **goal_id**, **action_item_id** |
| `scalepad_lm_meetings_update_v2` | write | Update core information about a meeting | **id** |
| `scalepad_lm_meeting_types_update` | write | Update a Meeting Type's label | **meeting_type_id**, **label** |
| `scalepad_lm_meeting_types_delete` | destructive | Delete a Meeting Type that is no longer relevant to business operations | **meeting_type_id** |
| `scalepad_lm_meeting_types_list` | read | List all Meeting Types currently available | - |
| `scalepad_lm_meeting_types_create` | write | Create a new Meeting Type with a label | **label** |
| `scalepad_lm_meetings_initiatives_list` | read | Get the IDs of initiatives that have been attached to a meeting | **meeting_id** |
| `scalepad_lm_meetings_initiatives_attach` | write | Attach an existing initiative to a meeting to include it as a discussion topic on the meeting | **meeting_id**, **initiative_id** |
| `scalepad_lm_meetings_initiatives_detach` | write | Detach an initiative and a meeting without deleting the initiative itself | **meeting_id**, **initiative_id** |
| `scalepad_lm_meetings_goals_list` | read | Get all goals that have been attached to a meeting | **meeting_id** |
| `scalepad_lm_meetings_goals_attach` | write | Attach an existing goal to a meeting to include it as a discussion topic on the meeting agenda | **meeting_id**, **goal_id** |
| `scalepad_lm_meetings_goals_detach` | write | Detach a goal and a meeting without deleting the goal itself, removing it from the meeting agenda | **meeting_id**, **goal_id** |
| `scalepad_lm_meetings_get` | read | Access complete details of a specific meeting | **id** |
| `scalepad_lm_meetings_update` | write | Update core information about a meeting | **id** |
| `scalepad_lm_meetings_delete` | destructive | Remove a meeting that is no longer needed | **id** |
| `scalepad_lm_meetings_create_v2` | write | Schedule a new client meeting | **client_key**, **title** |
| `scalepad_lm_meetings_list` | read | Get a comprehensive list of all client meetings with filtering options | - |
| `scalepad_lm_meetings_create` | write | Schedule a new client meeting | **client_key**, **title** |
| `scalepad_lm_meetings_completion_status_update` | write | Update the completion status of a meeting | **id**, **is_completed** |
| `scalepad_lm_meetings_user_attendees_remove` | write | Remove user attendees from the meeting | **id**, **user_keys** |
| `scalepad_lm_meetings_user_attendees_add` | write | Add users as meeting attendees | **id**, **user_keys** |
| `scalepad_lm_meetings_contact_attendees_remove` | write | Remove client contact attendees from the meeting | **id**, **contact_keys** |
| `scalepad_lm_meetings_contact_attendees_add` | write | Add one or more client contacts as attendees | **id**, **contact_keys** |
| `scalepad_lm_meetings_action_items_list` | read | Get all action items created during or linked to a specific meeting | **meeting_id** |
| `scalepad_lm_meetings_action_items_attach` | write | Attach an existing action item to a meeting to include it as a discussion topic or tracked | **meeting_id**, **action_item_id** |
| `scalepad_lm_meetings_action_items_detach` | write | Detach an action item and a meeting without deleting the action item itself | **meeting_id**, **action_item_id** |
| `scalepad_lm_action_items_reposition` | write | Reposition an action item within the account's manual sort order | **id** |
| `scalepad_lm_action_items_pin_update` | write | Pin or unpin an action item so it appears above other open action items in task lists | **id**, **is_pinned** |
| `scalepad_lm_action_items_completion_status_update` | write | Mark an action item as incomplete or completed to reflect the status of an action item | **id**, **is_completed** |
| `scalepad_lm_action_items_get` | read | Get an action item by the item's id | **id** |
| `scalepad_lm_action_items_update` | write | Update an existing action item with all necessary details for an action | **id**, **update_payload** |
| `scalepad_lm_action_items_delete` | destructive | Delete an action item that is no longer relevant to business operations | **id** |
| `scalepad_lm_action_items_list` | read | Get a list of action items | - |
| `scalepad_lm_action_items_create` | write | Create a new action item | **client_key**, **description** |
| `scalepad_lm_assessment_templates_get` | read | Get comprehensive details of a specific assessment template including all categories, questions | **assessment_template_id** |
| `scalepad_lm_assessment_templates_update` | write | Modify an existing assessment template including its structure, categories, questions | **assessment_template_id**, **assessment_template** |
| `scalepad_lm_assessment_templates_delete` | destructive | Archive an assessment template so it no longer appears in the active list | **assessment_template_id** |
| `scalepad_lm_assessment_templates_list` | read | Get a comprehensive list of all assessment template overviews for the account | - |
| `scalepad_lm_assessment_templates_create` | write | Create a new assessment template with custom categories, questions, and criteria | **assessment_template** |
| `scalepad_lm_assessments_question_public_comment_update` | write | Update the public comment on an assessment question | **assessment_id**, **question_id** |
| `scalepad_lm_assessments_question_internal_comment_update` | write | Update the internal comment on an assessment question | **assessment_id**, **question_id** |
| `scalepad_lm_assessments_internal_comment_update` | write | Leave an internal comment for an existing assessment | **id**, **internal_comment** |
| `scalepad_lm_assessments_evaluate` | write | Evaluate an assessment by selecting criteria for multiple questions | **id**, **question_evaluations** |
| `scalepad_lm_assessments_get` | read | Access complete details of a specific assessment including its evaluation | **id** |
| `scalepad_lm_assessments_update` | write | Update assessment details including title, evaluate user and datetime | **id** |
| `scalepad_lm_assessments_delete` | destructive | Permanently remove an assessment that is no longer relevant to business operations | **id** |
| `scalepad_lm_assessments_list` | read | Get a comprehensive list of all assessments overview with filtering options | - |
| `scalepad_lm_assessments_create` | write | Create a new assessment based on a assessment template | **client_key**, **title** |
| `scalepad_lm_assessments_completion_status_update` | write | Toggle an assessment's complete status | **id**, **is_completed** |
| `scalepad_lm_deliverables_pdf_get` | read | Download a PDF for the specified deliverable | **deliverable_id** |
| `scalepad_lm_deliverables_get` | read | Get a deliverable by its ID, including all sections and components | **deliverable_id** |
| `scalepad_lm_deliverables_update` | write | Update an existing deliverable with the provided fields | **deliverable_id** |
| `scalepad_lm_deliverables_delete` | destructive | Delete a deliverable by its ID, including all associated sections and components | **deliverable_id** |
| `scalepad_lm_deliverables_create_from_template` | write | Create a new deliverable by copying an existing template | **client_id**, **template_id** |
| `scalepad_lm_client_deliverables_list` | read | List all deliverable available for the specified client | **client_id** |
| `scalepad_lm_deliverables_create` | write | Create a new deliverable for the specified client | **client_id**, **name** |
| `scalepad_lm_deliverables_catalog_components_list` | read | List all deliverable catalog components available for the specified client | **client_id** |
| `scalepad_lm_deliverables_catalog_integrations_list` | read | List all available deliverable integrations in the catalog | - |
| `scalepad_lm_deliverables_integrated_integrations_list` | read | List deliverable integrations that are integrated for a client, including their configuration | **client_id** |
| `scalepad_lm_deliverables_presentation_get` | read | Get deliverable content and MSP branding for presentation | **deliverable_id** |
| `scalepad_lm_deliverables_sections_refresh` | write | Refresh the data of all the components under a deliverable section | **deliverable_id**, **section_id** |
| `scalepad_lm_deliverables_sections_delete` | destructive | Delete a deliverable section by its ID, including all associated components | **deliverable_id**, **section_id** |
| `scalepad_lm_deliverables_components_refresh` | write | Refresh the data of a deliverable section component | **deliverable_id**, **section_id**, **component_id** |
| `scalepad_lm_deliverables_components_delete` | destructive | Delete a deliverable section component by its ID | **deliverable_id**, **section_id**, **component_id** |
| `scalepad_lm_deliverable_templates_get` | read | Get a deliverable template by its ID, including all sections and components | **template_id** |
| `scalepad_lm_deliverable_templates_update` | write | Update an existing deliverable template with the provided fields | **template_id** |
| `scalepad_lm_deliverable_templates_delete` | destructive | Delete a deliverable template by its ID, including all associated sections and components | **template_id** |
| `scalepad_lm_deliverable_templates_duplicate` | write | Create a new deliverable template by copying an existing template | **template_id** |
| `scalepad_lm_deliverable_templates_create_from_deliverable` | write | Create a new deliverable template by extracting the structure from an existing deliverable | **deliverable_id** |
| `scalepad_lm_deliverable_templates_list` | read | List all deliverable templates available, including both ScalePad and custom templates | - |
| `scalepad_lm_deliverable_templates_create` | write | Create a new deliverable template for the account | **name** |
| `scalepad_lm_deliverable_templates_catalog_components_list` | read | List all deliverable catalog components available for use in templates | - |
| `scalepad_lm_deliverable_templates_sections_delete` | destructive | Delete a deliverable template section by its ID, including all associated components | **template_id**, **section_id** |
| `scalepad_lm_deliverable_templates_components_delete` | destructive | Delete a deliverable template section component by its ID | **template_id**, **section_id**, **component_id** |
| `scalepad_lm_deliverables_share_link_revoke` | destructive | Revoke the general share link for the specified deliverable | **deliverable_id** |
| `scalepad_lm_deliverables_share_link_regenerate` | destructive | Generate a new general share link for the specified deliverable | **deliverable_id** |
| `scalepad_lm_deliverables_share_link_get` | read | Get the general share link for a specific deliverable | **deliverable_id** |
| `scalepad_lm_deliverables_share_link_create` | write | Create a new general share link for the specified deliverable | **deliverable_id** |
| `scalepad_lm_deliverables_list` | read | List deliverables across the caller's account with optional client-scoped filtering, sorting | - |
| `scalepad_lm_budget_summary_get` | read | Get aggregate per-type totals for a client's budget forecast across the requested period window | **client_id** |
| `scalepad_lm_budget_it_debt_list` | read | List a client's IT Debt assets with per-period forecast amounts, sorted and paginated | **client_id** |
| `scalepad_lm_budget_initiatives_list` | read | List a client's initiatives with per-period forecast amounts, sorted and paginated | **client_id** |
| `scalepad_lm_budget_forecast_pdf_get` | read | Generate a PDF for a client's budget forecast (overview) | **client_id** |
| `scalepad_lm_budget_forecast_detail_pdf_get` | read | Generate a detailed PDF for a client's budget forecast | **client_id** |
| `scalepad_lm_budget_forecast_csv_get` | read | Generate a CSV export for a client's budget forecast | **client_id** |
| `scalepad_lm_budget_contracts_list` | read | List a client's contracts with per-period forecast amounts, sorted and paginated | **client_id** |
| `scalepad_lm_budget_availabilities_get` | read | Get the option lists used to construct Budget API queries for a single client | **client_id** |
| `scalepad_lm_contracts_get` | read | Get Contract | **id** |
| `scalepad_lm_contracts_update` | write | Update Contract | **id**, **update_payload** |
| `scalepad_lm_contracts_delete` | destructive | Delete Contract | **id** |
| `scalepad_lm_contracts_list` | read | List Contracts | - |
| `scalepad_lm_contracts_create` | write | Create Contract | **client_key**, **create_payload** |
| `scalepad_lm_contracts_assets_detach` | write | Detach Contract Assets | **contract_id**, **hardware_keys** |
| `scalepad_lm_contracts_assets_attach` | write | Attach Contract Assets | **contract_id**, **hardware_keys** |
| `scalepad_lm_user_identity_get` | read | User identity get (not available in the ScalePad API) | - |
| `scalepad_lm_ticket_create_fields_get` | read | Get the available PSA ticket creation fields for the primary PSA, including required | - |
| `scalepad_lm_opportunity_create_fields_get` | read | Get PSA opportunity create fields for a client, including integration availability | - |
| `scalepad_lm_opportunities_list` | read | List PSA opportunities for a client | - |
| `scalepad_lm_notes_get` | read | Get a note's full details | **id** |
| `scalepad_lm_notes_update` | write | Update title and description of a note | **id** |
| `scalepad_lm_notes_delete` | destructive | Delete a note | **id** |
| `scalepad_lm_notes_list` | read | Get a comprehensive list of all notes with filtering options | - |
| `scalepad_lm_notes_create` | write | Create a new note for a client | **client_key**, **title** |
| `scalepad_lm_notes_archive_status_update` | write | Mark the notes as archive or bring an archived notes back to active | **id**, **is_archived** |
| `scalepad_lm_user_ui_state_get` | read | User ui state get (not available in the ScalePad API) | **state_key** |
| `scalepad_lm_user_ui_state_put` | read | Put User UI State (not available in the ScalePad API) | **state_key**, **payload** |
| `scalepad_lm_insights_list` | read | Return the insights applicable to the requested client | - |
| `scalepad_lm_enrollment_tokens_create` | write | Create an enrollment token for a client | **client_id** |
| `scalepad_lm_saas_utilization_summary_get` | read | Return SaaS-utilization summary metrics for a client: app counts | **client_id** |

### ControlMap (98 tools)

| Tool | Kind | Purpose | Required |
|---|---|---|---|
| `scalepad_cm_health_list` | read | Return compliance health metrics for each client of an MSP | - |
| `scalepad_cm_health_get` | read | Return detailed compliance health metrics for a single MSP client | **client_id** |
| `scalepad_cm_reports_list` | read | Get a paginated list of reports for a client, with support for filtering with PII, sorting | **client_id** |
| `scalepad_cm_reports_get_signed_url` | read | Return metadata for a specific report document and a secure, time-limited pre-signed URL | **client_id**, **report_id** |
| `scalepad_cm_risks_search` | read | Get a paginated list of risks associated with a specific client | **client_id** |
| `scalepad_cm_risks_get` | read | Return detailed information for a specific risk identified by its ID for the given client | **client_id**, **risk_id** |
| `scalepad_cm_risks_create` | write | Create a new risk for the specified client with the provided details | **client_id**, **name** |
| `scalepad_cm_risks_update` | write | Update specific fields of a risk | **client_id**, **risk_id** |
| `scalepad_cm_risks_delete` | destructive | Delete an existing risk identified by its risk ID for the specified client | **client_id**, **risk_id** |
| `scalepad_cm_risks_list_summaries` | read | Return paginated risk summaries for all partner clients | - |
| `scalepad_cm_risks_map` | write | Map a risk to assets, asset types, threats, vulnerabilities, vendors, objectives, controls | **client_id**, **risk_id** |
| `scalepad_cm_risks_unmap` | write | Remove links between a risk and the given assets, asset types, threats, vulnerabilities | **client_id**, **risk_id** |
| `scalepad_cm_risks_get_category` | read | Return detailed information for a specific risk category identified by its ID | **client_id**, **risk_category_id** |
| `scalepad_cm_risks_list_departments` | read | Get all departments available for risk assignment for the specified client | **client_id** |
| `scalepad_cm_controls_search` | read | Get a paginated list of controls for a specific client | **client_id** |
| `scalepad_cm_controls_get` | read | Return detailed information for a specific control identified by its ID for the given client | **client_id**, **control_id** |
| `scalepad_cm_controls_create` | write | Create a control for for the specified client with the provided details | **client_id**, **name** |
| `scalepad_cm_controls_update` | write | Update specific fields of a control | **client_id**, **control_id** |
| `scalepad_cm_controls_delete` | destructive | Delete an existing Control identified by its control ID for the specified client | **client_id**, **control_id** |
| `scalepad_cm_controls_map` | write | Map policies, procedures, governance documents, risks, evidences, action items | **client_id**, **control_id** |
| `scalepad_cm_controls_unmap` | write | Remove links between a client control and policies, procedures, governance documents, risks | **client_id**, **control_id** |
| `scalepad_cm_controls_list_sets` | read | Return a paginated list of control sets for the client tenant | **client_id** |
| `scalepad_cm_controls_list_families` | read | Return a paginated list of control families for the client tenant | **client_id** |
| `scalepad_cm_controls_list_summaries` | read | Return paginated control summary metrics for all partner clients | - |
| `scalepad_cm_controls_get_summary` | read | Return aggregate control metrics for the requested client | **client_id** |
| `scalepad_cm_evidence_search` | read | Return a paginated list of evidences belonging to the specified client | **client_id** |
| `scalepad_cm_evidence_list_summaries` | read | Return paginated evidence summaries for all partner clients | - |
| `scalepad_cm_evidence_create` | write | Create a new evidence with all necessary details | **client_id**, **title** |
| `scalepad_cm_evidence_get` | read | Get detailed information about a specific evidence using its unique identifier | **client_id**, **evidence_id** |
| `scalepad_cm_evidence_update` | write | Partially update an existing evidence for the specified client | **client_id**, **evidence_id** |
| `scalepad_cm_evidence_delete` | destructive | Delete an evidence that is no longer required for compliance or business purposes | **client_id**, **evidence_id** |
| `scalepad_cm_evidence_delete_schedule` | destructive | Delete Evidence Schedule (Deprecated) | **client_id**, **evidence_id** |
| `scalepad_cm_evidence_requests_list` | read | Get all evidence requests and it's document associated with a specific evidence record | **client_id**, **evidence_id** |
| `scalepad_cm_evidence_requests_create` | write | Create a new request inside an existing evidence | **client_id**, **evidence_id** |
| `scalepad_cm_evidence_requests_create_with_urls` | write | Create an new evidence request and generates pre-signed URL(s) | **client_id**, **evidence_id**, **file_name**, **file_size_bytes** |
| `scalepad_cm_evidence_requests_signed_urls` | write | Generate pre-signed URL to upload document(s) for the specified evidence request | **client_id**, **evidence_request_id**, **file_name**, **file_size_bytes** |
| `scalepad_cm_evidence_requests_upload_document` | write | Upload a document up to 10 MB and attaches it to the specified evidence request | **client_id**, **evidence_request_id**, **file** |
| `scalepad_cm_evidence_requests_create_with_upload` | write | Create a new evidence request and uploads a document up to 10 MB | **client_id**, **evidence_id**, **file** |
| `scalepad_cm_evidence_requests_create_link` | write | Create a new hyperlink and associates it with an evidence request | **client_id**, **evidence_request_id**, **name**, **hyperlink** |
| `scalepad_cm_evidence_requests_update` | write | Update specific fields of an evidence request | **client_id**, **evidence_request_id** |
| `scalepad_cm_evidence_requests_delete` | destructive | Delete a specific evidence request associated with an evidence | **client_id**, **evidence_request_id** |
| `scalepad_cm_evidence_requests_archive` | write | Archive an existing evidence request and records audit metadata | **client_id**, **evidence_request_id** |
| `scalepad_cm_evidence_refresh_mappings` | write | Trigger a refresh of all evidence mappings for the specified client | **client_id** |
| `scalepad_cm_documents_get_signed_url` | read | Get a time-limited signed URL for downloading the specified document | **client_id**, **document_id** |
| `scalepad_cm_documents_delete` | destructive | Delete the specified document for the given client | **client_id**, **document_id** |
| `scalepad_cm_evidence_map` | write | Map an evidence to objectives and/or controls for a client | **client_id**, **evidence_id** |
| `scalepad_cm_evidence_unmap` | write | Remove links between an evidence and the given objectives (requirements) and/or controls | **client_id**, **evidence_id** |
| `scalepad_cm_governance_search` | read | Get a paginated list of governance for a specific client | **client_id** |
| `scalepad_cm_governance_create` | write | Create a new governance for the specified client with the provided details | **client_id**, **title** |
| `scalepad_cm_governance_get` | read | Return detailed information for a specific governance identified by its ID for the given client | **client_id**, **governance_id** |
| `scalepad_cm_governance_update` | write | Update specific fields of a governance | **client_id**, **governance_id** |
| `scalepad_cm_governance_delete` | destructive | Delete an existing governance identified by its governance ID for the specified client | **client_id**, **governance_id** |
| `scalepad_cm_governance_map` | write | Map a governance to framework requirements (objectives), policies, and/or controls for a client | **client_id**, **governance_id** |
| `scalepad_cm_governance_unmap` | write | Remove links between a client governance and given objectives (requirements), policies | **client_id**, **governance_id** |
| `scalepad_cm_governance_list_summaries` | read | Return paginated governance summaries for all partner clients | - |
| `scalepad_cm_policies_search` | read | Get a paginated list of policies for a specific client | **client_id** |
| `scalepad_cm_policies_create` | write | Create a new policy for the specified client with the provided details | **client_id**, **title** |
| `scalepad_cm_policies_get` | read | Return detailed information for a specific policy identified by its ID for the given client | **client_id**, **policy_id** |
| `scalepad_cm_policies_update` | write | Update specific fields of a policy | **client_id**, **policy_id** |
| `scalepad_cm_policies_delete` | destructive | Delete an existing policy identified by its policy ID for the specified client | **client_id**, **policy_id** |
| `scalepad_cm_policies_upsert_section` | write | Create or updates an HTML policy section using title and description (snake_case JSON) | **client_id**, **policy_id**, **title** |
| `scalepad_cm_policies_delete_section` | destructive | Delete an existing policy section identified by its section ID for the specified client policy | **client_id**, **policy_id**, **section_id** |
| `scalepad_cm_policies_map` | write | Map a policy to framework objectives and/or controls for a client | **client_id**, **policy_id** |
| `scalepad_cm_policies_unmap` | write | Remove links between a client policy and the framework objectives and/or controls in the request | **client_id**, **policy_id** |
| `scalepad_cm_policies_list_summaries` | read | Return paginated Policy summaries for all partner clients | - |
| `scalepad_cm_procedures_search` | read | Get a paginated list of procedures for a specific client | **client_id** |
| `scalepad_cm_procedures_create` | write | Create a new procedure for the specified client with the provided details | **client_id**, **title** |
| `scalepad_cm_procedures_get` | read | Return detailed information for a specific procedure identified by its ID for the given client | **client_id**, **procedure_id** |
| `scalepad_cm_procedures_update` | write | Update specific fields of a procedure document (procedure rows only, not governance documents) | **client_id**, **procedure_id** |
| `scalepad_cm_procedures_delete` | destructive | Delete an existing procedure identified by its procedure ID for the specified client | **client_id**, **procedure_id** |
| `scalepad_cm_procedures_map` | write | Map a client procedure to framework requirements (objectives), policies, and/or controls | **client_id**, **procedure_id** |
| `scalepad_cm_procedures_unmap` | write | Remove links between a client procedure and framework requirements (objectives), policies | **client_id**, **procedure_id** |
| `scalepad_cm_procedures_list_summaries` | read | Return paginated Procedure summaries for all partner clients | - |
| `scalepad_cm_objectives_search` | read | Get a paginated list of objectives associated with a specific client | **client_id**, **framework_id** |
| `scalepad_cm_objectives_get` | read | Return a single objective for the specified client and framework | **client_id**, **framework_id**, **objective_id** |
| `scalepad_cm_objectives_get_summary` | read | Return Objective summary for a single client | **client_id** |
| `scalepad_cm_objectives_list_summaries` | read | Return paginated Objective summaries for all partner clients | - |
| `scalepad_cm_assessments_list_summaries` | read | Return paginated Assessment Overview for all partner clients | - |
| `scalepad_cm_assessments_get_summary` | read | Return comprehensive assessment summary for a client | **client_id** |
| `scalepad_cm_assessments_search_questions` | read | Return a paginated list of assessment questions for the specified client | **client_id** |
| `scalepad_cm_assessments_get_question` | read | Return full assessment question details for the question identified by question code | **client_id**, **question_code** |
| `scalepad_cm_assessments_save_answer` | write | Submit or updates the selected answer for the assessment question identified by question_code | **client_id**, **question_code**, **answer** |
| `scalepad_cm_assessments_clear_answer` | destructive | Clear the existing answer for the specified assessment question | **client_id**, **question_code** |
| `scalepad_cm_assessments_map_question` | write | Map an assessment question to evidences, action items, policies, or procedures for a client | **client_id**, **question_code** |
| `scalepad_cm_assessments_unmap_question` | write | Unmap Assessment Question from Items (Deprecated) | **client_id**, **question_code** |
| `scalepad_cm_assessments_create_response` | write | Create a response for a client's assessment question | **client_id**, **question_code**, **response** |
| `scalepad_cm_assessments_update_response` | write | Partially update a question response | **client_id**, **question_code**, **id** |
| `scalepad_cm_assessments_delete_response` | destructive | Delete a assessment question response | **client_id**, **question_code**, **response_id** |
| `scalepad_cm_action_items_search` | read | Get a paginated list of action items for a specific client | **client_id** |
| `scalepad_cm_action_items_get` | read | Get a specific action item for a given client | **client_id**, **action_item_id** |
| `scalepad_cm_action_items_create` | write | Create a new action item for the specified client with the provided details Allowed values | **client_id**, **weakness_name** |
| `scalepad_cm_action_items_update` | write | Update specific fields of an action item request | **client_id**, **action_item_id** |
| `scalepad_cm_action_items_delete` | destructive | Delete an existing action item identified by its action item ID for the specified client | **client_id**, **action_item_id** |
| `scalepad_cm_action_items_map` | write | Map an action item to objectives, assessment questions, risks, controls, assets | **client_id**, **action_item_id** |
| `scalepad_cm_action_items_unmap` | write | Remove links between an action item and the given objectives (requirements) | **client_id**, **action_item_id** |
| `scalepad_cm_action_items_upload_document` | write | Upload a document up to 10 MB and associates it with the specified action item | **client_id**, **action_item_id**, **file** |
| `scalepad_cm_action_items_generate_signed_urls` | write | Generate pre-signed URL(s) to upload document(s) for the specified action item | **client_id**, **action_item_id**, **file_name**, **file_size_bytes** |
| `scalepad_cm_action_items_list_summaries` | read | Get a paginated summary of action items grouped by client | - |

### Backup Radar (3 tools)

| Tool | Kind | Purpose | Required |
|---|---|---|---|
| `scalepad_br_backups_list_health` | read | Return a cursor-paginated list of clients whose backup health matches the optional filters | - |
| `scalepad_br_backups_get_health` | read | Return backup health for one client | **id** |
| `scalepad_br_backups_list_devices` | read | Return a cursor-paginated list of backup devices whose names match the optional filters | - |

### Quoter (61 tools)

| Tool | Kind | Purpose | Required |
|---|---|---|---|
| `scalepad_quoter_quotes_list` | read | Get a paginated list of all Quotes | - |
| `scalepad_quoter_quotes_get` | read | Get a quote revision with the full display payload - sections, line items, totals, contacts | **quote_id** |
| `scalepad_quoter_quotes_create` | write | Create a new draft quote from a template | **contact**, **template_id** |
| `scalepad_quoter_quotes_publish` | write | Transition a draft quote into the published state | **quote_id** |
| `scalepad_quoter_quotes_create_section` | write | Add one or more sections to a draft quote | **quote_id**, **name** |
| `scalepad_quoter_quotes_create_section_line_item` | write | Add one or more line items to a section on a draft quote | **quote_id**, **section_id**, **name** |
| `scalepad_quoter_quotes_update_line_item` | write | Patch a line item on a draft quote | **quote_id**, **section_id**, **line_item_id** |
| `scalepad_quoter_line_items_create` | write | Create Line Item | **quote_id**, **name** |
| `scalepad_quoter_quote_templates_list` | read | Get a paginated list of all Quote Templates | - |
| `scalepad_quoter_categories_list` | read | Get a list of all categories available in the system | - |
| `scalepad_quoter_categories_create` | write | Add a new category to organize items | **name** |
| `scalepad_quoter_categories_get` | read | Get detailed information about a specific category | **id** |
| `scalepad_quoter_categories_update` | write | Modify the properties or configuration of an existing category | **id** |
| `scalepad_quoter_categories_delete` | destructive | Remove a category from the system | **id** |
| `scalepad_quoter_item_group_assignments_list` | read | Get a list of all item group assignments available in the system | - |
| `scalepad_quoter_item_group_assignments_create` | write | Assign an item to an item group | **item_group_id**, **item_id** |
| `scalepad_quoter_item_group_assignments_get` | read | Get detailed information about a specific item group assignment | **id** |
| `scalepad_quoter_item_group_assignments_delete` | destructive | Remove an item group assignment from the system | **id** |
| `scalepad_quoter_item_groups_list` | read | Get a list of all item groups available in the system | - |
| `scalepad_quoter_item_groups_create` | write | Add a new item group to organize items | **name** |
| `scalepad_quoter_item_groups_get` | read | Get detailed information about a specific item group | **id** |
| `scalepad_quoter_item_groups_update` | write | Modify the properties or configuration of an existing item group | **id** |
| `scalepad_quoter_item_groups_delete` | destructive | Remove an item group from the system | **id** |
| `scalepad_quoter_item_option_values_list` | read | Get a list of all item option values available in the system | - |
| `scalepad_quoter_item_option_values_create` | write | Add a new value to an item option | **item_option_id**, **name** |
| `scalepad_quoter_item_option_values_get` | read | Get detailed information about a specific item option value | **id** |
| `scalepad_quoter_item_option_values_update` | write | Modify the properties or configuration of an existing item option value | **id** |
| `scalepad_quoter_item_option_values_delete` | destructive | Remove an item option value from an item option | **id** |
| `scalepad_quoter_item_options_list` | read | Get a list of all item options available in the system | - |
| `scalepad_quoter_item_options_create` | write | Add a new item option to an item | **item_id**, **name** |
| `scalepad_quoter_item_options_get` | read | Get detailed information about a specific item option | **id** |
| `scalepad_quoter_item_options_update` | write | Modify the properties or configuration of an existing item option | **id** |
| `scalepad_quoter_item_options_delete` | destructive | Remove an item option from an item | **id** |
| `scalepad_quoter_item_tiers_list` | read | Get a list of all item tiers available in the system | - |
| `scalepad_quoter_item_tiers_create` | write | Add a new pricing tier to an item | **item_id** |
| `scalepad_quoter_item_tiers_get` | read | Get detailed information about a specific item tier | **id** |
| `scalepad_quoter_item_tiers_update` | write | Modify the properties or configuration of an existing item tier | **id** |
| `scalepad_quoter_item_tiers_delete` | destructive | Remove an item tier from an item | **id** |
| `scalepad_quoter_items_list` | read | Get a list of all items available in the system | - |
| `scalepad_quoter_items_create` | write | Add a new item to your product catalog | **name**, **category_id** |
| `scalepad_quoter_items_get` | read | Get detailed information about a specific item | **id** |
| `scalepad_quoter_items_update` | write | Modify the properties or configuration of an existing item | **id** |
| `scalepad_quoter_items_delete` | destructive | Remove an item from your product catalog | **id** |
| `scalepad_quoter_manufacturers_list` | read | Get a list of all manufacturers available in the system | - |
| `scalepad_quoter_manufacturers_create` | write | Add a new manufacturer to the system | **name** |
| `scalepad_quoter_manufacturers_get` | read | Get detailed information about a specific manufacturer | **id** |
| `scalepad_quoter_manufacturers_update` | write | Modify the properties or configuration of an existing manufacturer | **id** |
| `scalepad_quoter_manufacturers_delete` | destructive | Remove a manufacturer from the system | **id** |
| `scalepad_quoter_contacts_list` | read | Get a list of contacts | - |
| `scalepad_quoter_contacts_create` | write | Create a new contact with billing and optional shipping details | - |
| `scalepad_quoter_contacts_get` | read | Get a contact by its id | **id** |
| `scalepad_quoter_contacts_update` | write | Update a specific contact's information by its id | **id** |
| `scalepad_quoter_suppliers_list` | read | Get a list of all suppliers available in the system | - |
| `scalepad_quoter_suppliers_create` | write | Add a new supplier to the system | **name** |
| `scalepad_quoter_suppliers_get` | read | Get detailed information about a specific supplier | **id** |
| `scalepad_quoter_suppliers_update` | write | Modify the properties or configuration of an existing supplier | **id** |
| `scalepad_quoter_suppliers_delete` | destructive | Remove a supplier from the system | **id** |
| `scalepad_quoter_datafeeds_list_supplier_items` | read | Get supplier item data for specified MPNs from suppliers configured through SupplierSync | - |
| `scalepad_quoter_datafeeds_list_suppliers` | read | Get a list of suppliers configured through SupplierSync | - |
| `scalepad_quoter_auth_authorize` | read | Auth authorize (not available in the ScalePad API) | - |
| `scalepad_quoter_auth_refresh` | read | Auth refresh (not available in the ScalePad API) | **refresh_token** |

Errors come back as a JSON envelope instead of an exception:

```json
{"error": {"code": "unauthorized", "message": "ScalePad returned HTTP 402 for /lifecycle-manager/v1/contacts: PRODUCT_SUBSCRIPTION_REQUIRED Lifecycle Manager subscription required ...", "retryable": false}}
```

`code` is one of `not_configured`, `unauthorized`, `not_found`, `invalid_argument`,
`rate_limited`, `upstream_error`; ScalePad's error `code`, `title` and `detail` are included.
Reads are retried with backoff on 429 (honouring `Retry-After`), 5xx and network errors;
writes are retried only on 429, so a write never runs twice.

## Run locally

```bash
uv sync
uv run python -m scalepad_mcp          # listens on 0.0.0.0:8080
```

or with Docker:

```bash
docker build --platform linux/amd64 -t scalepad-mcp:dev .
docker run --rm -p 8080:8080 scalepad-mcp:dev
```

Configuration (environment variables, all optional): `MCP_HTTP_HOST` (default `0.0.0.0`),
`MCP_HTTP_PORT` (default `8080`), `LOG_LEVEL` (default `INFO`). The key is never read from the
environment.

## Testing example

```bash
# list tools
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-ScalePad-Api-Key: your-api-key" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# clients whose name matches
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-ScalePad-Api-Key: your-api-key" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"scalepad_core_clients_list","arguments":{"filter":{"name":"Example"},"page_size":10}}}'
```

Unit tests (no network access needed):

```bash
uv run pytest
```

## Delivery notes

- **Tool count (381).** Kept as is because the tool names and parameters are an existing
  contract (`tests/contract.json` pins every name and its required parameters).
- **Declarative tools.** Every tool is one entry in `src/scalepad_mcp/catalog.py` (method, path,
  where each argument goes) built from the ScalePad API reference; one engine turns calls into
  requests, and a test checks every entry against its path template.
- **Endpoints that did not exist.** Older versions called eight Lifecycle Manager routes that are
  not in the ScalePad API. Five now use the official equivalents: contact lookup (contacts list
  filtered by client), active users (`/users`), initiative and goal updates (`PATCH`, with
  plain-text summaries converted to rich text) and client-group lookup (reads the client groups
  and keeps those listing the client). Three have no public endpoint and return an explanatory
  `invalid_argument`: `scalepad_lm_user_identity_get`, `scalepad_lm_user_ui_state_get` and
  `scalepad_lm_user_ui_state_put`. The Quoter OAuth helpers (`scalepad_quoter_auth_authorize`,
  `scalepad_quoter_auth_refresh`) are not needed with the ScalePad key and do the same.
- **Request shapes.** Bodies follow the official schemas: section and line-item creation and
  signed-URL requests send a one-element array, document uploads are multipart (the `file`
  argument is base64), reference fields such as `client_key`, `hardware_key`, `category`,
  `manufacturer` and `supplier` are objects but a bare id string is still accepted and wrapped
  as `{"id": ...}`, and ControlMap `fields` lists are joined into the comma-separated string the
  API expects.
- **Safety annotations.** Deletes are annotated destructive; attach / detach, map / unmap and
  other changes are writes; descriptions tell the agent to use them only on explicit request.
- **No interactive prompts.** Older versions asked the user for filters or confirmation
  mid-call, which a stateless gateway cannot relay; lists page instead, and write tools rely on
  their descriptions and annotations.

## License

Apache License 2.0 - see [LICENSE](LICENSE) and [NOTICE](NOTICE).
