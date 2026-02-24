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
