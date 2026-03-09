"""
db/redis_store.py — Backward-compatible re-export shim.

All Redis logic now lives in the db/redis/ package (domain-split modules).
This file exists solely so that existing imports like:

    from db.redis_store import get_conversation, save_preferences, ...

continue to work without any changes to callers.

To add new Redis operations: add them to the appropriate db/redis/<domain>.py
module and add a re-export here.
"""

# Re-export everything from the new package — zero logic lives here
from db.redis import (  # noqa: F401
    # Infrastructure
    _r,
    _json_get,
    _json_set,
    PROPERTY_INFO_TTL,
    SEARCH_IDS_TTL,
    LANGUAGE_TTL,
    ANALYTICS_TTL,
    LAST_SEARCH_TTL,
    # Conversation domain
    get_conversation,
    save_conversation,
    clear_conversation,
    set_active_request,
    get_active_request,
    delete_active_request,
    set_last_agent,
    get_last_agent,
    set_account_values,
    get_account_values,
    clear_account_values,
    set_whitelabel_pg_ids,
    get_whitelabel_pg_ids,
    # User domain
    save_preferences,
    get_preferences,
    set_user_name,
    get_user_name,
    set_user_phone,
    get_user_phone,
    set_no_message,
    get_no_message,
    clear_no_message,
    set_user_language,
    get_user_language,
    set_aadhar_user_name,
    get_aadhar_user_name,
    delete_aadhar_user_name,
    set_aadhar_gender,
    get_aadhar_gender,
    delete_aadhar_gender,
    detect_persona,
    update_persona,
    get_user_memory,
    save_user_memory,
    update_user_memory,
    _calculate_lead_score,
    get_lead_temperature,
    record_property_viewed,
    record_property_shortlisted,
    record_visit_scheduled,
    add_deal_breaker,
    build_returning_user_context,
    FUNNEL_ORDER,
    # Property domain
    set_property_info_map,
    get_property_info_map,
    set_last_search_results,
    get_last_search_results,
    get_shortlisted_properties,
    save_property_template,
    get_property_template,
    clear_property_template,
    set_property_images_id,
    get_property_images_id,
    clear_property_images_id,
    set_image_urls,
    get_image_urls,
    clear_image_urls,
    set_property_id_for_search,
    get_property_id_for_search,
    clear_property_id_for_search,
    # Analytics domain
    save_feedback,
    get_feedback_counts,
    track_agent_usage,
    get_agent_usage,
    track_skill_usage,
    track_skill_miss,
    get_skill_usage,
    get_skill_misses,
    track_funnel,
    get_funnel,
    increment_agent_cost,
    get_agent_costs,
    increment_daily_cost,
    get_daily_cost,
    set_response,
    get_response,
    FUNNEL_STAGES,
    # Payment domain
    set_payment_info,
    get_payment_info,
    clear_payment_info,
    schedule_followup,
    get_due_followups,
    complete_followup,
    cancel_followups,
    # Brand domain
    _brand_hash,
    get_brand_config,
    set_brand_config,
    get_brand_wa_config,
    get_brand_by_token,
    # Admin domain
    get_active_users,
    get_active_users_count,
    get_human_mode,
    set_human_mode,
    clear_human_mode,
    increment_session_cost,
    get_session_cost,
)
