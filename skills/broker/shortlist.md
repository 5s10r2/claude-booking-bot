---
skill: shortlist
tools: [shortlist_property]
depends: []
description: "Save/bookmark a property to user's shortlist"
---

<instructions>
When user wants to shortlist/save/bookmark a property:
- Call shortlist_property with the exact property name
- Confirm with enthusiasm: "Saved! [Property] is on your shortlist"
- Immediately offer next step: schedule a visit, compare with another, or keep browsing
</instructions>

<example>
<user>Shortlist Jyoti Sparkle</user>
<assistant>
[call shortlist_property(property_name="Jyoti Sparkle O2 Andheri")]

Done! ⭐ **Jyoti Sparkle O2 Andheri** is saved to your shortlist.

Want to schedule a visit there, or keep looking at other options?
</assistant>
</example>

<example>
<user>Save Green Heights too</user>
<assistant>
[call shortlist_property(property_name="Green Heights Andheri")]

Added! ⭐ **Green Heights Andheri** is on your shortlist alongside Jyoti Sparkle.

You've got two solid picks saved. Want me to compare them side-by-side to help you decide, or schedule visits at both?
</assistant>
</example>
