# Historical evaluation baseline

This is a recorded result from the original implementation, before the 1.1.0 release fixes.
It has not been rerun against the updated prompts, privacy document or runtime limits.
The answer text from that run was not supplied; this summary cannot establish semantic
correctness of every passing answer. Web search was disabled.

# Eval report

Run at 2026-11-14T23:36:38.

## Recorded score: 28 of 30 passed the rule-based checks

Model `openai/gpt-oss-120b`, web search off. Median response time 12.1s. Tokens used: 128,778 in, 7,163 out.

| Category | Correct |
|---|---|
| documents | 13 of 14 |
| listings | 8 of 9 |
| multi-step | 3 of 3 |
| not-found | 4 of 4 |

| ID | Result | Question | Sources cited | Why it failed |
|---|---|---|---|---|
| doc-01 | pass | What commission do you charge for selling a home? | fees-and-commission.md |  |
| doc-02 | pass | How much does your buying-agent service cost? | fees-and-commission.md |  |
| doc-03 | pass | If my income is too low, what does a guarantor need to earn? | rental-policy.md |  |
| doc-04 | pass | How big is the security deposit for a rental, and how fast do I get it back if there is no damage? | rental-policy.md |  |
| doc-05 | pass | After I sign the purchase agreement, how long can I still change my mind? | buying-guide.md |  |
| doc-06 | pass | How late can I cancel a viewing appointment? | viewings-and-bidding.md |  |
| doc-07 | pass | Can I just phone in my bid on a house? | viewings-and-bidding.md |  |
| doc-08 | pass | On average, how quickly did the homes you sold in 2025 find a buyer? | selling-guide.md |  |
| doc-09 | pass | What do your clients pay for mortgage advice at Hypotheek Kompas? | mortgage-advice.md |  |
| doc-10 | pass | Is the Amsterdam office open on Saturdays? | offices-and-contact.md |  |
| doc-11 | **FAIL** | My heating broke down at night in the apartment you manage. What number do I call? | - | did not cite: offices-and-contact.md |
| doc-12 | pass | As a landlord, what is your management fee and up to what amount can you do repairs without asking me? | property-management.md, property-management.md |  |
| doc-13 | pass | How long does it take you to give a proper reply to a complaint? | handover-and-complaints.md |  |
| doc-14 | pass | I applied for a rental but did not get it. How long do you keep my documents? | privacy-and-data.md |  |
| lst-01 | pass | What is the asking price of listing NL-1005? | NL-1005 |  |
| lst-02 | pass | Which homes for sale in Utrecht cost less than €500,000? | NL-1003, NL-1001 |  |
| lst-03 | pass | Which of your rental listings allow pets? | NL-2002, NL-2006, NL-2003 |  |
| lst-04 | pass | Do you have a houseboat for sale, and what are the yearly mooring fees? | NL-1007 |  |
| lst-05 | pass | Until when has the ground rent been bought off for the apartment on Cruquiusweg? | NL-1006 |  |
| lst-06 | pass | What is the cheapest home you have for sale in Amersfoort? | NL-1011 |  |
| lst-07 | pass | Which homes for sale in Rotterdam come with private parking? | NL-1012 |  |
| lst-08 | **FAIL** | Is the penthouse in Leidsche Rijn still available? | - | answer is missing: under offer; did not cite: NL-1004 |
| lst-09 | pass | I am looking for a house to buy with at least 4 bedrooms and solar panels. What do you have? | NL-1002, NL-1010 |  |
| mix-01 | pass | If NL-1002 sells for exactly its asking price, what would your selling commission be? | NL-1002, fees-and-commission.md |  |
| mix-02 | pass | What gross monthly income do I need to rent listing NL-2002? | NL-2002, rental-policy.md |  |
| mix-03 | pass | How much security deposit would I pay for the studio near Utrecht Science Park? | NL-2001, rental-policy.md |  |
| neg-01 | pass | What discount do you give to sellers who have sold with you before? | - |  |
| neg-02 | pass | Who is the managing director of Noorderlicht Makelaars? | - |  |
| neg-03 | pass | Do you have any homes for sale in Groningen? | - |  |
| neg-04 | pass | What did Merelstraat 17 sell for the last time it changed owners? | - |  |

## Document search: right document in the top 5 for 17 of 17 questions

Right document ranked first for 17 of 17; mean reciprocal rank 1.0. Covers the questions whose answer is in a company document; listing questions go through SQL filters instead.

