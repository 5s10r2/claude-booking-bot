from db.redis_store import get_conversation, save_conversation


class ConversationManager:
    def get_history(self, user_id: str) -> list[dict]:
        return get_conversation(user_id)

    def add_user_message(self, user_id: str, content: str) -> list[dict]:
        messages = self.get_history(user_id)
        messages.append({"role": "user", "content": content})
        save_conversation(user_id, messages)
        return messages

    def add_assistant_message(self, user_id: str, content: str) -> list[dict]:
        messages = self.get_history(user_id)
        messages.append({"role": "assistant", "content": content})
        save_conversation(user_id, messages)
        return messages

    def clear(self, user_id: str) -> None:
        from db.redis_store import clear_conversation
        clear_conversation(user_id)
