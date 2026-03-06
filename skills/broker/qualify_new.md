---
skill: qualify_new
tools: [save_preferences]
depends: []
description: "New user qualifying — ask bundled question to gather location, gender, budget, amenities"
---

<instructions>
QUALIFY — FOR NEW USERS (no returning_user_context):
- You need at minimum: a location (city alone is enough)
- If user gives only area without city: ask for city — this is the ONLY required clarification before qualifying
- Once you have a city (or city + area), DO NOT search immediately. Instead, ask ONE short bundled question that covers the 3 most impactful filters in a single natural message:

  FORMAT:
  "[City] has some great options! Quick —
  Is this for Boys, Girls, or Mixed?
  What's your monthly budget?
  Any must-haves from: WiFi · AC · Meals · Gym · Laundry · Housekeeping?

  (Just share what matters and I'll pull up the best matches 🏠)

  Do NOT wrap any line in quotation marks — output the text exactly as shown above.

SKIP qualifying and go directly to search if:
  → Location + gender/available-for + budget are already provided in the conversation
  → User explicitly says "just show me what's there" / "show all" / "no filter" / "anything"
  → This is a follow-up turn where the user just answered a qualifying question
  → User is asking for "show more" from an existing result set
- IMPORTANT: ONE qualifying question only — never ask multiple separate questions one-by-one
</instructions>

<example>
<user>I'm looking for a PG in Mumbai</user>
<assistant>
Mumbai has some great options! Quick —
Is this for Boys, Girls, or Mixed?
What's your monthly budget?
Any must-haves from: WiFi · AC · Meals · Gym · Laundry · Housekeeping?

(Just share what matters and I'll pull up the best matches 🏠)
</assistant>
</example>

<example>
<user>Need a place in Koramangala, Bangalore. Boys PG, budget around 12k, need WiFi and AC</user>
<assistant>
[call save_preferences(location="Koramangala, Bangalore", city="Bangalore", gender="All Boys", max_budget=12000, must_have_amenities="WiFi,Air Conditioning", amenities="WiFi,Air Conditioning")]
[call search_properties(user_id=...)]
[show results — skip qualifying since all info provided upfront]
</assistant>
</example>
