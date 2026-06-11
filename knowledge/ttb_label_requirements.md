# TTB Alcohol Beverage Label Requirements (Core Mandatory Information)

This file provides concise, citable grounding for local LLM analysis of OMB No. 1513-0020 (TTB F 5100.31) COLA submissions. It focuses on the most common mandatory elements that must appear on labels for wines (27 CFR Part 4), distilled spirits (Part 5), and malt beverages (Part 7), plus the health warning (Part 16).

**Important**: This is an aid for triage and analysis only. It does not replace official TTB review, the full eCFR, or professional legal advice. Always verify against current regulations. The LLM should quote verbatim evidence from the OCR transcript and cite specific sections.

## Health Warning Statement (27 CFR Part 16, Alcoholic Beverage Labeling Act)
Required on all alcoholic beverages containing 0.5% or more alcohol by volume, for sale or distribution in the United States.

**Exact required text** (must appear as a continuous paragraph; "GOVERNMENT WARNING" must be in bold capital letters; the entire statement is typically required in all capital letters for the warning body in many approved labels, though the statute specifies the content):

GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems.

**Verification points for analysis**:
- The statement must be present.
- It must match the statutory content (minor punctuation/line-break tolerance may exist in practice, but the core clauses must be there).
- Prominence and type size rules apply (see 27 CFR 16.21 and 16.22); the LLM should note if the OCR suggests it is hard to read or not prominent.
- Must not be obscured.

**Code-enforceable bright line (keep in verify.py)**: Exact or near-exact match to the statutory text + all-caps check on the warning body.

## Common Mandatory Label Information (most commodities)
These generally must appear on the brand label or a separate label in accordance with the applicable part:

1. **Brand Name** (27 CFR 4.33, 5.32/5.33, 7.64 etc.)
   - The name under which the product is marketed.
   - Must be prominent. If no brand, the name of the producer/bottler may serve in some cases.
   - Must not be misleading.

2. **Class and Type Designation** (27 CFR Part 4 Subpart C for wine, Part 5 Subpart C for spirits, 7.141+ for malt beverages)
   - Must accurately identify the product (e.g., "Red Wine", "Vodka", "American Lager", "Table Wine", specific standards of identity).
   - For wine: often includes grape variety, appellation of origin, vintage when claimed.
   - For spirits: specific class/type (whiskey, gin, rum, etc.) with aging statements where required.
   - Must be on the label in required type size and format.

3. **Alcohol Content** (percentage alcohol by volume)
   - Required for many products; format is typically "X% alc./vol." or similar approved statements.
   - For wine: often "X% by vol." or "X% alc./vol."
   - Must match the actual product and any claims on the application form.

4. **Net Contents** (27 CFR 4.37, 5.38, 7.70 etc.)
   - Statement of quantity (e.g., "750 mL", "1.75 L", "375 mL", "12 fl. oz.").
   - Must be accurate and in required format/location (sometimes blown/embossed on container).

5. **Name and Address** of the bottler, packer, producer, or importer (as applicable)
   - Domestic: name and address of the bottling/packing premises or principal place of business.
   - Imported: name and address of the importer, and often the foreign producer.
   - "Bottled by", "Packed by", "Imported by", "Produced by" phrasing must be accurate per the form.

6. **Country of Origin**
   - Required for imported products (before or after importation in many cases).
   - Must be clear (e.g., "Product of Spain", "Made in France").

## Additional Common / Commodity-Specific Items (LLM should flag when relevant from OCR or form)
- Sulfite declaration ("Contains sulfites" or equivalent) when applicable (wine and some others).
- "Contains" major food allergen statements (modern TTB expectations in some contexts).
- For wine: vintage date, appellation, grape variety, estate bottled, etc., when claimed — must meet strict definitional rules (Part 4).
- For distilled spirits: age statements, "bottled in bond", specific type designations, coloring/flavoring disclosures.
- For malt beverages: class/type per 27 CFR 7, some have additional statements.
- Prohibited practices: misleading claims, certain health claims, incorrect net contents, etc.
- Type size, legibility, contrast, and placement rules (e.g., brand name minimum sizes, warning statement visibility).

## How the LLM Should Use This for Analysis
Given the full OCR transcript(s) of the submission (form pages + label artwork):
- Detect the primary commodity: wine, distilled spirits, or malt beverage (from form fields like "class/type", "type of wine", "kind of spirits", ABV range, or explicit statements).
- Extract key declarations from the *application/form* portion.
- Analyze the *label artwork* text blocks for presence, accuracy, and consistency with declarations and the rules above.
- For each major requirement, output:
  - Requirement name / citation
  - Status: pass / fail / missing / info / needs_review
  - Verbatim evidence quote(s) from the OCR (preserve original casing/punctuation as much as possible)
  - Notes on any mismatch between form declaration and label text
  - Any observed issues with prominence, format, or additional text that may conflict
- Always include the health warning analysis (use or reference the deterministic check).
- Output overall: "likely_compliant", "issues_found", or "needs_human_review".
- Be conservative: if evidence is unclear due to OCR quality, mark "needs_review" and quote the raw text.
- Never invent regulatory text; stick to the excerpts here plus the provided transcript.

## Notes for This Tool
- The original prototype only performed limited form-vs-label field matching + strict health warning check.
- This broadened version uses LLM analysis of the raw OCR to cover more requirements while still surfacing all raw text and evidence for human oversight.
- The health warning remains a code-enforced bright-line item because it is a strict statutory requirement with a precise text.

Sources for grounding: Public TTB guidance, 27 CFR Parts 4, 5, 7, 16, and form instructions for TTB F 5100.31 (OMB 1513-0020). Update this file when regulations change.

---
Last updated: 2026-06-11 (for LabelCompare broadened scope)
