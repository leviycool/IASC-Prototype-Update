# IASC Donor Analytics — Data Dictionary

This document defines every field in the three database tables: **contacts**, **gifts**, and **interactions**.
Source systems are:
- **Salesforce** — CRM; primary record of donors, gift history, and contact metadata.
- **MailChimp** — Email marketing platform; supplies email engagement metrics.
- **WealthEngine** — Prospect research tool; supplies estimated giving capacity scores.
- **Hedgehog Review** — Subscriber database; source for subscriber_only contacts and the `hedgehog_review_subscriber` flag.
- **Derived** — Calculated from other fields within this system; not ingested from an external source.

---

## Table: contacts

One row per person. This is the primary record linking all donor, subscriber, and prospect data.

### Core identity and geography

| Field | Data Type | Source | Description | Example Values | NULL Handling |
|---|---|---|---|---|---|
| `contact_id` | TEXT (PK) | Salesforce | Salesforce-format 18-character unique identifier for the contact. | `003XX00000AbCd1234` | Never NULL; primary key. |
| `first_name` | TEXT | Salesforce | Contact's first (given) name. | `Mary`, `Rajesh`, `Wei` | Never NULL. |
| `last_name` | TEXT | Salesforce | Contact's last (family) name. | `Johnson`, `Patel`, `Okafor` | Never NULL. |
| `email` | TEXT | Salesforce | Primary email address used for communications and MailChimp list membership. | `mary.johnson42@example.com` | NULL if no email on file; ~4% of contacts. |
| `city` | TEXT | Salesforce | City of the contact's mailing address. | `New York`, `Charlottesville`, `Chicago` | NULL if address is incomplete; ~32% of contacts (especially subscriber_only). |
| `state` | TEXT | Salesforce | Two-letter US state abbreviation of the contact's mailing address. | `VA`, `NY`, `DC` | NULL if address is incomplete. |
| `zip_code` | TEXT | Salesforce | 5-digit US ZIP code of the contact's mailing address. | `22901`, `10001`, `20001` | NULL if address is incomplete. |

### Donor status and dates

| Field | Data Type | Source | Description | Example Values | NULL Handling |
|---|---|---|---|---|---|
| `donor_status` | TEXT | Derived | Categorical giving status: `active` (gave within last 2 years), `lapsed` (gave 2+ years ago), `new_donor` (first gift within ~18 months), `prospect` (no gift on record), `subscriber_only` (Hedgehog Review subscriber with no Salesforce giving record). | `active`, `lapsed`, `prospect`, `new_donor`, `subscriber_only` | Never NULL; derived at data load time. |
| `contact_created_date` | DATE | Salesforce | Date the contact record was created in Salesforce; proxy for when IASC first became aware of this person. | `2010-03-15`, `2019-11-01` | Rarely NULL; defaults to import date if unknown. |
| `first_gift_date` | DATE | Salesforce | Date of the contact's earliest recorded gift. | `1998-12-12`, `2015-06-03` | NULL for prospects and subscriber_only (no giving history). |
| `last_gift_date` | DATE | Salesforce | Date of the contact's most recent gift. | `2024-11-28`, `2021-03-10` | NULL for prospects. For lapsed donors, normally earlier than 2024-02-25 (see intentional data quality issues). |

### Gift summary fields

| Field | Data Type | Source | Description | Example Values | NULL Handling |
|---|---|---|---|---|---|
| `total_gifts` | REAL | Salesforce | Cumulative lifetime giving amount in USD. | `250.00`, `15000.00`, `1200000.00` | NULL for prospects and subscriber_only. |
| `total_number_of_gifts` | INTEGER | Salesforce | Total count of individual gift transactions on record. | `1`, `12`, `47` | NULL for prospects and subscriber_only. |
| `average_gift` | REAL | Derived | Mean gift amount: `total_gifts / total_number_of_gifts`. | `125.00`, `1250.00` | NULL for prospects and subscriber_only. |
| `giving_vehicle` | TEXT | Salesforce | Predominant method used for gifts: `check`, `online`, `stock`, `DAF` (donor-advised fund), or `wire`. | `online`, `DAF`, `stock` | NULL for prospects and subscriber_only. |

### Subscription fields

| Field | Data Type | Source | Description | Example Values | NULL Handling |
|---|---|---|---|---|---|
| `subscription_type` | TEXT | Salesforce | Type of Hedgehog Review subscription: `print`, `digital`, `both`, or `none`. | `digital`, `print`, `both`, `none` | Never NULL; `none` if no subscription exists. |
| `subscription_status` | TEXT | Salesforce | Current subscription state: `active`, `expired`, or `never` (no subscription of this type was ever held). | `active`, `expired`, `never` | Never NULL. |
| `subscription_start_date` | DATE | Salesforce | Date the contact's first subscription began. | `2008-09-01`, `2021-01-15` | NULL when `subscription_type` is `none`. |

### Email engagement

| Field | Data Type | Source | Description | Example Values | NULL Handling |
|---|---|---|---|---|---|
| `email_open_rate` | REAL | MailChimp | Proportion of emails opened over the contact's lifetime in MailChimp (0.0–1.0). | `0.28`, `0.05`, `0.71` | NULL for contacts not on the MailChimp list, with email_opt_out=1, or who are deceased. |
| `last_email_click_date` | DATE | MailChimp | Date the contact last clicked a link in a MailChimp email. | `2024-08-14`, `2023-12-01` | NULL if the contact has never clicked, has opted out, or MailChimp data is unavailable. |

### Events and capacity

| Field | Data Type | Source | Description | Example Values | NULL Handling |
|---|---|---|---|---|---|
| `event_attendance_count` | INTEGER | Salesforce | Total number of IASC events (galas, lectures, receptions) the contact has attended, as logged in Salesforce. | `0`, `2`, `7` | Never NULL; defaults to 0 for contacts with no event history. |
| `wealth_score` | INTEGER | WealthEngine | Estimated philanthropic giving capacity on a 1–10 scale (10 = highest capacity), sourced from WealthEngine screening. | `3`, `7`, `10` | NULL for a significant portion of contacts not yet screened by WealthEngine (~35% no-match rate). |
| `notes` | TEXT | Salesforce | Free-text notes entered by development staff, such as meeting context, referral source, or communication preferences. | `Met at conference 2019`, `Prefers email contact` | NULL for most contacts with no recorded notes (~70%). |

### Financial scoring fields (WealthEngine / prospect research)

| Field | Data Type | Source | Description | Example Values | NULL Handling |
|---|---|---|---|---|---|
| `p2g_score` | INTEGER | WealthEngine | Propensity-to-give score on a 1–99 scale; higher scores indicate stronger likelihood of making a gift. Loosely correlated with giving history and wealth score. | `72`, `15`, `88` | NULL for ~60% of contacts not yet screened. Absence does not mean low propensity. |
| `gift_capacity_rating` | TEXT | WealthEngine | Categorical estimate of giving capacity: `Major` (top ~2%), `Mid-Level` (next ~8%), `Entry-Level` (next ~30%). Derived from p2g_score and wealth_score. | `Major`, `Mid-Level`, `Entry-Level` | NULL for ~60% of contacts (mirrors WealthEngine screening coverage). |
| `estimated_annual_donations` | REAL | WealthEngine | Estimated total annual charitable giving by this contact across ALL organizations (not just IASC), in USD. Typically 2–50× the contact's actual IASC giving rate, since people give to many organizations. | `5000.00`, `50000.00`, `250.00` | NULL for ~60% of contacts. |

### Biographical fields (staff-researched)

| Field | Data Type | Source | Description | Example Values | NULL Handling |
|---|---|---|---|---|---|
| `title` | TEXT | Salesforce | Professional title or honorific, as entered by development staff. | `Professor`, `Attorney`, `Retired`, `CEO`, `Judge` | NULL for ~85% of contacts; populated only for actively cultivated donors and prospects. |
| `deceased` | INTEGER | Salesforce | Boolean flag (1 = deceased, 0 = living). Deceased contacts must have `donor_status` of `lapsed`, `prospect`, or `subscriber_only`; `subscription_status` of `expired` or `never`; and NULL email engagement fields. | `0`, `1` | Never NULL; defaults to 0. |
| `biography` | TEXT | Salesforce | Short free-text biographical note entered by development staff (1–2 sentences). Describes professional background and connection to IASC. | `Professor of English at UVA; longtime supporter of humanities scholarship.` | NULL for ~90% of contacts. |
| `business_affiliations` | TEXT | Salesforce | Professional directorships or organizational affiliations. | `Board of Directors, Charlottesville Symphony Orchestra` | NULL for ~92% of contacts. |
| `community_affiliations` | TEXT | Salesforce | Civic and community involvement. | `Rotary Club of Charlottesville; UVA Alumni Association` | NULL for ~93% of contacts. |
| `expertise_and_interests` | TEXT | Salesforce | Areas of intellectual interest relevant to IASC's mission, as noted by staff. | `Cultural criticism, higher education policy`, `Religious history, Southern literature` | NULL for ~88% of contacts; more likely populated for active subscribers and donors. |

### Contact preference and compliance fields

| Field | Data Type | Source | Description | Example Values | NULL Handling |
|---|---|---|---|---|---|
| `do_not_contact` | INTEGER | Salesforce | Boolean flag (1 = do not contact by any method). If 1, also implies `do_not_call=1` and `email_opt_out=1`. | `0`, `1` | Never NULL; defaults to 0. ~5% of contacts. |
| `do_not_call` | INTEGER | Salesforce | Boolean flag (1 = do not call by phone). Superset of do_not_contact. | `0`, `1` | Never NULL; defaults to 0. ~8% of contacts. |
| `email_opt_out` | INTEGER | Salesforce | Boolean flag (1 = contact has opted out of email communications). If 1, `email_open_rate` and `last_email_click_date` are NULL. | `0`, `1` | Never NULL; defaults to 0. ~12% of contacts. |
| `preferred_phone` | TEXT | Salesforce | Contact's preferred phone type for outreach. | `Home`, `Mobile`, `Work` | NULL for ~70% of contacts (preference not recorded). |
| `preferred_email` | TEXT | Salesforce | Contact's preferred email type for outreach. | `Personal`, `Work` | NULL for ~65% of contacts (preference not recorded). |

### IASC-specific relationship fields

| Field | Data Type | Source | Description | Example Values | NULL Handling |
|---|---|---|---|---|---|
| `hedgehog_review_subscriber` | INTEGER | Derived | Boolean flag (1 = confirmed Hedgehog Review subscriber). Always 1 when `subscription_type != 'none'`, plus an additional ~40% of others who are subscribers in the separate HR subscriber database but may not have an active subscription_type recorded. Reflects real data fragmentation between Salesforce and the HR subscriber system. | `0`, `1` | Never NULL; defaults to 0. |
| `institute_status` | TEXT | Salesforce | Formal relationship to the Institute for Advanced Studies in Culture: `Board Member` (~0.2%), `Fellow` (~1%), `Affiliate` (~2.6%), `Friend` (~9%), `None` (remainder). | `Fellow`, `Affiliate`, `None` | Never NULL; `None` for contacts with no formal relationship. |
| `foundation_status` | TEXT | Derived | Relationship to the IASC Foundation (the fundraising entity). Derived from giving history: `Major Donor` (total_gifts ≥ $10,000), `Annual Donor` (total_gifts ≥ $100), `Prospect` (no giving history), `None` (gave but under $100). | `Major Donor`, `Annual Donor`, `Prospect`, `None` | Never NULL. |
| `lead_source` | TEXT | Salesforce | How the contact first entered the database. | `Hedgehog Review`, `Event`, `Board Referral`, `Website`, `Email Campaign`, `Direct Mail`, `Other` | NULL for ~2% of contacts (source not recorded). |

### Derived gift detail fields

These fields are computed from the `gifts` table after generation. They are stored on the contact record for query convenience.

| Field | Data Type | Source | Description | Example Values | NULL Handling |
|---|---|---|---|---|---|
| `largest_gift` | REAL | Derived | Largest single gift amount in the contact's giving history. | `50000.00`, `1000.00` | NULL for prospects and subscriber_only (no gift history). |
| `smallest_gift` | REAL | Derived | Smallest single gift amount in the contact's giving history. | `25.00`, `100.00` | NULL for prospects and subscriber_only. |
| `best_gift_year` | INTEGER | Derived | Calendar year in which the contact's total giving was highest. | `2022`, `2019` | NULL for prospects and subscriber_only. |
| `last_gift_amount` | REAL | Derived | Dollar amount of the contact's most recent gift. | `500.00`, `10000.00` | NULL for prospects and subscriber_only. |

---

## Table: gifts

One row per individual gift transaction. Prospects and subscriber_only contacts have no rows in this table. The sum of `amount` per `contact_id` equals that contact's `total_gifts` in the contacts table (to within $0.01 due to rounding).

| Field | Data Type | Source | Description | Example Values | NULL Handling |
|---|---|---|---|---|---|
| `gift_id` | INTEGER (PK) | Derived | Auto-incrementing surrogate key for the gift transaction. | `1`, `42`, `1807` | Never NULL; primary key. |
| `contact_id` | TEXT (FK) | Salesforce | Foreign key referencing `contacts.contact_id`; identifies the donor who made this gift. | `003XX00000AbCd1234` | Never NULL; every gift belongs to a contact. |
| `gift_date` | DATE | Salesforce | Date the gift was received or processed by IASC. Biased toward November–December (year-end giving season). | `2023-12-15`, `2021-11-02` | Never NULL. |
| `amount` | REAL | Salesforce | Dollar value of this individual gift in USD. Always ≥ $1.00. | `100.00`, `5000.00`, `250000.00` | Never NULL. |
| `gift_type` | TEXT | Salesforce | Categorization of the gift: `one_time`, `recurring` (part of a pledge or installment plan), `planned_giving` (bequest or deferred gift), or `event` (ticket purchase / event-linked gift). | `one_time`, `recurring` | NULL if not yet categorized in Salesforce. |
| `campaign` | TEXT | Salesforce | Name of the fundraising campaign the gift is attributed to, as entered in Salesforce. | `Year-End Appeal 2023`, `Spring Gala 2022`, `Annual Fund 2021` | NULL for unrestricted or unattributed gifts (~25% of rows). |

---

## Table: interactions

One row per logged touchpoint between IASC staff (or systems) and a contact. The volume of interactions per contact is loosely correlated with email engagement and event attendance. Prospects and low-engagement donors may have zero rows.

| Field | Data Type | Source | Description | Example Values | NULL Handling |
|---|---|---|---|---|---|
| `interaction_id` | INTEGER (PK) | Derived | Auto-incrementing surrogate key for the interaction record. | `1`, `88`, `2450` | Never NULL; primary key. |
| `contact_id` | TEXT (FK) | Salesforce / MailChimp | Foreign key referencing `contacts.contact_id`; identifies the contact involved in this interaction. | `003XX00000AbCd1234` | Never NULL; every interaction belongs to a contact. |
| `interaction_date` | DATE | Salesforce / MailChimp | Date the interaction occurred or was logged. | `2023-04-10`, `2024-11-30` | Never NULL. |
| `interaction_type` | TEXT | Derived | Categorical type of interaction: `email_open`, `email_click` (from MailChimp), `event_attended`, `meeting`, `phone_call`, or `mail_sent` (from Salesforce). | `email_open`, `meeting`, `event_attended` | Never NULL. |
| `details` | TEXT | Salesforce / MailChimp | Free-text description of the interaction — campaign name for email events, event name for attendance, brief note for meetings and calls. | `Year-End Appeal 2023`, `Spring Gala 2022`, `Cultivation lunch` | NULL for a minority of interactions where no additional detail was recorded. |

---

## Notes on NULL handling and data quality

1. **Prospects and subscriber_only vs. donors.** Contacts with `donor_status = 'prospect'` or `'subscriber_only'` have NULL in all gift-related fields (`first_gift_date`, `last_gift_date`, `total_gifts`, `total_number_of_gifts`, `average_gift`, `giving_vehicle`, `largest_gift`, `smallest_gift`, `best_gift_year`, `last_gift_amount`). Query tools must handle this explicitly to avoid filtering out these segments when they are relevant.

2. **subscriber_only contacts are data-sparse.** These records simulate contacts imported from the Hedgehog Review subscriber database who have never interacted with the Foundation directly. They typically have: name, maybe an email (~80%), maybe a state/zip (~70%), subscription fields, and `hedgehog_review_subscriber=1`. Most other fields are NULL, including all wealth and biographical fields.

3. **WealthEngine coverage.** A significant portion of contacts lack `wealth_score`, `p2g_score`, `gift_capacity_rating`, and `estimated_annual_donations` because WealthEngine screening is not run on every record (~35–60% no-match rates depending on field). Absence of these scores does not imply low capacity; it means the contact has not yet been screened. Treat NULL scores as missing, not as zero.

4. **MailChimp coverage.** Contacts with `email_opt_out=1` or `deceased=1` have NULL `email_open_rate` and `last_email_click_date`. Contacts not on the MailChimp list may also have NULL engagement fields.

5. **`average_gift` is derived.** It is stored for query convenience but is always equal to `total_gifts / total_number_of_gifts`. Do not treat it as an independent field; recompute from the gifts table for transaction-level analysis.

6. **`donor_status` is derived at load time.** It is not a field that development staff manually maintain. Changes to giving history (e.g., a lapsed donor makes a new gift) require re-running `generate_mock_data.py` or updating this field via a recalculation script.

7. **Gift amounts in the gifts table.** Individual gift `amount` values are generated to approximate `average_gift` per contact but will not match exactly due to rounding. The sum of amounts per contact is guaranteed to equal `total_gifts` to within $0.01.

8. **Date constraints (normal).** `first_gift_date` is normally ≤ `last_gift_date`. `contact_created_date` is normally ≤ `first_gift_date` for donors. For lapsed donors, `last_gift_date` is normally before 2024-02-25 (more than 2 years before the prototype's reference date of 2026-02-25). See intentional data quality issues below for deliberate exceptions.

9. **Compliance flags interact.** `do_not_contact=1` implies both `do_not_call=1` and `email_opt_out=1`. `email_opt_out=1` implies NULL email engagement fields. Always check `do_not_contact` before including a contact in any outreach analysis.

---

## Intentional data quality issues

The synthetic dataset includes deliberate inconsistencies that mirror real nonprofit data problems. These are documented here so analysts can verify they found them and use them as test cases for data cleaning pipelines.

### Issue 1: Missing email contacts (~3% of total contacts)

A subset of contacts has `email = NULL`. These contacts were imported from sources where email was not captured (e.g., event sign-in sheets, direct mail returns). They are unreachable by email.

**How to find them:**
```sql
SELECT COUNT(*) FROM contacts WHERE email IS NULL;
```

### Issue 2: Deceased contacts with active subscriptions (~10% of deceased contacts with subscriptions)

Some contacts marked `deceased=1` still have `subscription_status = 'active'`. This simulates records that were not updated after a donor's death — a common problem in small nonprofits where the database may not be reviewed systematically after receiving a death notification.

**How to find them:**
```sql
SELECT contact_id, first_name, last_name, deceased, subscription_status
FROM contacts
WHERE deceased = 1 AND subscription_status = 'active';
```

### Issue 3: Date inversions (~1% of donors)

A small number of donor contacts have `last_gift_date < first_gift_date`. This simulates data entry errors where the dates were entered in the wrong fields (e.g., a staff member swapped the values). Any analysis comparing `first_gift_date` to `last_gift_date` should validate this constraint first.

**How to find them:**
```sql
SELECT contact_id, first_name, last_name, first_gift_date, last_gift_date
FROM contacts
WHERE last_gift_date < first_gift_date;
```

### Issue 4: Wrong lapsed status (~5% of lapsed donors)

Some contacts with `donor_status = 'lapsed'` have a `last_gift_date` within the last 2 years (i.e., after 2024-02-25). These contacts should be reclassified as `active` but were not updated — simulating stale derived fields that accumulate when the database is not regularly recalculated.

**How to find them:**
```sql
SELECT contact_id, first_name, last_name, last_gift_date
FROM contacts
WHERE donor_status = 'lapsed' AND last_gift_date > '2024-02-25';
```

### Issue 5: Near-duplicate records (~6 injected pairs)

Six contacts from the main dataset were duplicated with slightly different emails and zip codes. This simulates the merge problem Andrew described, where the same person appears in both Salesforce and the Hedgehog Review subscriber database with slightly different contact information.

Note: because the name pool is finite, additional natural name collisions also exist in the data (two contacts with the same first and last name are not necessarily the same person). The 6 injected pairs are distinguishable because the duplicate shares the same first_name, last_name, and state/city, with only the email and zip code differing.

**How to find potential near-duplicates:**
```sql
SELECT first_name, last_name, COUNT(*) as n
FROM contacts
GROUP BY first_name, last_name
HAVING n > 1
ORDER BY n DESC;
```
