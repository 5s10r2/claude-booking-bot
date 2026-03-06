---
skill: show_more
tools: [search_properties, fetch_properties_by_query]
depends: []
description: "Show next batch of results or expand search radius"
---

<instructions>
SHOW MORE HANDLING:
- If there are unshown results from the last search → show next 5 from existing results
- If ALL results have already been shown (e.g. the search only returned 2–5 total and you already showed them all), then on ANY "show more" / "show others" / "anything else?" request: IMMEDIATELY call search_properties with radius_flag=true — do NOT repeat properties already listed
- Keep numbering continuous across batches (e.g. if first batch was 1–5, next starts at 6)
</instructions>

<example>
<user>Show me more options</user>
<assistant>
Here are the next ones! 🏠

**6. Comfort Stay Malad**
📍 Malad West · ₹11,000/mo · Boys · ~5.2 km
⭐ Match: 82%

**7. Metro View PG**
📍 Goregaon East · ₹10,500/mo · Boys · ~4.8 km
⭐ Match: 80%

**8. Sunrise Residency**
📍 Andheri East · ₹13,000/mo · Boys · ~2.9 km
⭐ Match: 78%

These are slightly farther but great value. Want details on any, or should I compare your favorites?
</assistant>
</example>

<example>
<user_context>User has seen all results from the initial search (only 3 matched). Needs expanded radius.</user_context>
<user>Any other options?</user>
<assistant>
[call search_properties(user_id=..., radius_flag=true)]

Expanded the search area — here are more options! 🏠

**4. Metro Connect PG**
📍 Malad West · ₹10,500/mo · Boys · ~6.1 km from Andheri
⭐ Match: 81%

**5. Horizon Stay**
📍 Goregaon East · ₹11,000/mo · Boys · ~5.5 km from Andheri
⭐ Match: 79%

**6. Silver Oak Residency**
📍 Jogeshwari West · ₹9,800/mo · Boys · ~3.8 km from Andheri
⭐ Match: 77%

Silver Oak in Jogeshwari is the closest — and at ₹9.8k, it's the best value of the lot. Want to compare it with your earlier favorites?
</assistant>
</example>
