# ⚠️  DEAD CODE — NOT REGISTERED IN TOOLS REGISTRY
# This tool is NOT wired into any agent and will never be called by Claude.
# DO NOT register without first resolving the security issue below.
#
# SECURITY: load_vectorstore_from_redis() uses allow_dangerous_deserialization=True
# which deserializes arbitrary Python pickle data from Redis. If Redis is compromised
# or the faiss:*:pkl keys are poisoned, this leads to remote code execution.
# Safe alternatives: store embeddings as numpy arrays (no pickle), use pgvector,
# or re-embed at query time from sanitised raw text stored in Redis.
#
# To reactivate safely:
# 1. Replace pickle-based FAISS storage with a safe embedding store.
# 2. Register the tool in tools/registry.py for the appropriate agent.
from db.redis_store import load_vectorstore_from_redis


async def query_knowledge_base(
    user_id: str, query: str, file_hash: str = "", **kwargs
) -> str:
    if not file_hash:
        return "No knowledge base loaded. Please upload documents first."

    vectorstore = load_vectorstore_from_redis(file_hash)
    if vectorstore is None:
        return "Knowledge base not found. Please re-upload documents."

    try:
        docs = vectorstore.similarity_search(query, k=4)
    except Exception as e:
        return f"Error searching knowledge base: {str(e)}"

    if not docs:
        return "No relevant information found in the knowledge base for your query."

    results = []
    for i, doc in enumerate(docs, 1):
        content = doc.page_content.strip()
        if content:
            results.append(f"[{i}] {content}")

    return "Relevant information from knowledge base:\n\n" + "\n\n".join(results)
